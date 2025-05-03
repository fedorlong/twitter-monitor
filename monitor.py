# monitor.py
import os
import requests
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import Header
import json
from dotenv import load_dotenv
import time
import datetime
import pytz
from supabase import create_client, Client

# === Load .env ===
load_dotenv()

# === Config ===
# TWITTER_USERNAME 现在从环境变量中读取并处理
# LAST_TWEET_FILE 已移除
# 设置监控时间范围（太平洋时间）
MONITOR_START_HOUR = 7  # 早上7点开始
MONITOR_END_HOUR = 11   # 早上11点结束
# Supabase 配置
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
SUPABASE_TABLE = "monitored_tweets" # Supabase 表名
SUPABASE_HISTORY_TABLE = "notification_history" # 通知历史记录表名

# === Supabase Client ===
supabase: Client = None
try:
    if SUPABASE_URL and SUPABASE_KEY:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
        print("Supabase client initialized successfully.")
    else:
        print("Error: SUPABASE_URL and SUPABASE_KEY must be set in environment variables.")
        exit(1) # 如果 Supabase 配置不完整则退出
except Exception as e:
    print(f"Error initializing Supabase client: {e}")
    exit(1)

# === Helper: Get Latest Tweet (使用Twitter API) ===
def get_latest_tweet_api(username): # 接受 username 参数
    try:
        import tweepy

        # Twitter API凭据 (从环境变量获取)
        api_key = os.environ.get('TWITTER_API_KEY')
        api_secret = os.environ.get('TWITTER_API_SECRET')
        access_token = os.environ.get('TWITTER_ACCESS_TOKEN')
        access_secret = os.environ.get('TWITTER_ACCESS_SECRET')
        bearer_token = os.environ.get('TWITTER_BEARER_TOKEN')

        print(f"Fetching latest tweet for: {username}...")

        # OAuth 1.0a (用户认证)
        if all([api_key, api_secret, access_token, access_secret]):
            print("Using OAuth 1.0a authentication...")
            auth = tweepy.OAuth1UserHandler(api_key, api_secret, access_token, access_secret)
            api = tweepy.API(auth)

            tweets = api.user_timeline(screen_name=username, count=1, tweet_mode="extended")
            if tweets:
                tweet = tweets[0]
                tweet_id = tweet.id_str
                tweet_url = f"https://x.com/{username}/status/{tweet_id}"
                tweet_text = tweet.full_text
                created_at = tweet.created_at
                print(f"Successfully fetched tweet (OAuth 1.0a), created at: {created_at}")
                print(f"Tweet content: {tweet_text[:50]}..." if len(tweet_text) > 50 else f"Tweet content: {tweet_text}")
                return {'id': tweet_id, 'url': tweet_url, 'text': tweet_text, 'created_at': str(created_at)}

        # OAuth 2.0 (应用认证)
        elif bearer_token:
            print("Using OAuth 2.0 Bearer Token authentication...")
            client = tweepy.Client(bearer_token=bearer_token)

            user = client.get_user(username=username)
            if not user or not user.data:
                print(f"Could not get user info for {username}")
                return None

            user_id = user.data.id
            tweets = client.get_users_tweets(
                id=user_id,
                max_results=5, # API v2 minimum is 5
                tweet_fields=['created_at', 'text']
            )

            if tweets and tweets.data:
                tweet = tweets.data[0]
                tweet_id = tweet.id
                tweet_url = f"https://x.com/{username}/status/{tweet_id}"
                tweet_text = tweet.text
                created_at = tweet.created_at
                print(f"Successfully fetched tweet (OAuth 2.0), created at: {created_at}")
                print(f"Tweet content: {tweet_text[:50]}..." if len(tweet_text) > 50 else f"Tweet content: {tweet_text}")
                return {'id': str(tweet_id), 'url': tweet_url, 'text': tweet_text, 'created_at': str(created_at)}
            else:
                print(f"No tweets found for {username}")

        else:
            print("Missing necessary Twitter API credentials.")
            print("Please set either (TWITTER_API_KEY, TWITTER_API_SECRET, TWITTER_ACCESS_TOKEN, TWITTER_ACCESS_SECRET) or TWITTER_BEARER_TOKEN in .env")

        return None
    except Exception as e:
        print(f"Twitter API request failed for {username}: {e}")
        return None

# === Helper: State (已移除 load_last_id 和 save_last_id) ===

# === Send Email ===
def send_email(tweet, recipient_email, monitored_username): # 接受 recipient_email 和 monitored_username
    smtp_server = 'smtp.gmail.com'
    smtp_port = 587
    sender = os.environ['EMAIL_SENDER']
    password = os.environ['EMAIL_PASSWORD']

    subject = f"Twitter 更新通知：@{monitored_username} 发新推文" # 在主题中包含用户名

    if 'text' in tweet:
        body = f"""
发现 @{monitored_username} 的新推文：

内容: {tweet['text']}

链接: {tweet['url']}

时间: {tweet.get('created_at', '未知')}
        """
    else:
        body = f"发现 @{monitored_username} 的新推文：{tweet['url']}"

    msg = MIMEMultipart()
    msg['From'] = sender
    msg['To'] = recipient_email
    msg['Subject'] = Header(subject, 'utf-8')
    msg.attach(MIMEText(body, 'plain', 'utf-8'))

    try:
        server = smtplib.SMTP(smtp_server, smtp_port)
        print(f"aaa")
        server.starttls()
        print(f"bbb")
        server.login(sender, password)
        print(f"ccc")
        server.send_message(msg)
        print(f"ddd")
        server.quit()
        print(f"Email sent successfully to {recipient_email} for @{monitored_username}")
    except Exception as e:
        print(f"Failed to send email to {recipient_email} for @{monitored_username}: {e}")

# === Feishu Notification ===
def get_tenant_access_token():
    """获取飞书 tenant_access_token"""
    try:
        token_url = 'https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal/'
        token_data = {
            'app_id': os.environ['FEISHU_APP_ID'],
            'app_secret': os.environ['FEISHU_APP_SECRET']
        }
        
        token_resp = requests.post(
            token_url,
            headers={'Content-Type': 'application/json'},
            json=token_data
        )
        
        token_result = token_resp.json()
        if token_result.get('code') != 0:
            print(f"获取tenant_access_token失败: {token_result}")
            return None
            
        tenant_token = token_result.get('tenant_access_token')
        print(f"已获取tenant_access_token: {tenant_token[:10]}...")
        return tenant_token
    except Exception as e:
        print(f"获取tenant_access_token时出错: {e}")
        return None

def build_message_content(tweet, monitored_username): # 接受 monitored_username
    """构建飞书消息内容"""
    message_content = f"🔔 X(Twitter)更新提醒 🔔\n\n"
    message_content += f"用户: @{monitored_username}\n\n" # 使用传入的用户名
    
    if 'text' in tweet:
        message_content += f"内容: {tweet['text']}\n\n"
        
    if 'created_at' in tweet:
        message_content += f"时间: {tweet['created_at']}\n\n"
        
    message_content += f"链接: {tweet['url']}"
    return message_content

def send_feishu_message(tenant_token, message_content, feishu_user_id): # 接受 feishu_user_id
    """发送飞书消息并返回消息ID"""
    try:
        headers = {
            'Authorization': f'Bearer {tenant_token}',
            'Content-Type': 'application/json'
        }
        
        message_data = {
            "receive_id": feishu_user_id, # 使用传入的用户ID
            "content": json.dumps({"text": message_content}),
            "msg_type": "text"
        }
        
        send_url = "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=user_id"
        send_response = requests.post(send_url, headers=headers, json=message_data)
        send_result = send_response.json()
        
        print(f"Feishu message sent result: Status={send_response.status_code}, Response={send_result}")
        
        if send_result.get('code') == 0 and 'data' in send_result and 'message_id' in send_result['data']:
            message_id = send_result['data']['message_id']
            print(f"Message sent successfully, message_id: {message_id}")
            # 返回 headers 以便后续加急使用
            return message_id, headers
        else:
            print(f"Failed to send message: {send_result.get('msg', 'Unknown error')}")
            return None, None
    except Exception as e:
        print(f"Error sending Feishu message: {e}")
        return None, None

def send_urgent_phone_call(message_id, headers, feishu_user_id): # 接受 feishu_user_id
    """发送电话加急通知"""
    try:
        print(f"Sending urgent phone call for message {message_id} to user {feishu_user_id}...")
        
        urgent_url = f"https://open.feishu.cn/open-apis/im/v1/messages/{message_id}/urgent_phone?user_id_type=user_id"
        
        urgent_data = {
            "user_id_list": [feishu_user_id] # 使用传入的用户ID
        }
        
        urgent_response = requests.patch(urgent_url, headers=headers, json=urgent_data)
        
        if urgent_response.text.strip():
            urgent_result = urgent_response.json()
            if urgent_result.get('code') == 0:
                print("Urgent phone call sent successfully!")
                return True
            else:
                error_code = urgent_result.get('code')
                error_msg = urgent_result.get('msg', 'Unknown error')
                print(f"Failed to send urgent phone call: code={error_code}, msg={error_msg}")
                return False
        else:
            print("Urgent phone call response was empty.")
            return False # 或者根据需要处理空响应
    except Exception as e:
        print(f"Error sending urgent phone call: {e}")
        return False

def check_message_read_status(message_id, headers, feishu_user_id): # 接受 feishu_user_id
    """检查消息是否已读 (特定用户)"""
    try:
        # 注意：此接口可能仍需要确认是否能有效针对特定用户检查，文档似乎暗示返回所有已读用户
        # 但我们简化逻辑，只检查数组是否为空
        status_url = f"https://open.feishu.cn/open-apis/im/v1/messages/{message_id}/read_users?user_id_type=user_id"
        params = {'user_id_type': 'user_id'} # 明确指定参数

        status_response = requests.get(status_url, headers=headers, params=params) # 使用 params
        status_result = status_response.json()

        if status_result.get('code') == 0:
            read_users = status_result.get('data', {}).get('items', [])
            # 简化逻辑：只要items数组长度大于0就表示目标用户可能已读 (因为我们只通知一个人)
            # 更严谨的检查: is_read = any(user.get('user_id') == feishu_user_id for user in read_users)
            is_read = len(read_users) > 0 # 保持简化逻辑

            if is_read:
                 # 获取第一个已读用户的时间戳 (假设就是我们的目标用户)
                read_time = read_users[0].get('timestamp')
                if read_time:
                    try:
                        read_time_ms = int(read_time)
                        read_time_sec = read_time_ms / 1000
                        read_time_str = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(read_time_sec))
                        print(f"Message read status check: Read (at {read_time_str})")
                    except ValueError:
                         print(f"Message read status check: Read (invalid timestamp: {read_time})")
                else:
                    print("Message read status check: Read (timestamp missing)")
            else:
                print("Message read status check: Not read")

            return is_read
        else:
            error_code = status_result.get('code')
            error_msg = status_result.get('msg', 'Unknown error')
            print(f"Failed to check message read status: code={error_code}, msg={error_msg}")
            return False # 失败时假定未读可能更安全
    except Exception as e:
        print(f"Error checking message read status: {e}")
        return False

def retry_urgent_phone_call(message_id, headers, feishu_user_id, max_retries=2, wait_seconds=90): # 接受 feishu_user_id
    """重试发送电话加急通知"""
    retry_count = 0
    
    while retry_count < max_retries:
        print(f"Waiting {wait_seconds}s before checking read status (Retry {retry_count + 1}/{max_retries})...")
        time.sleep(wait_seconds)

        is_read = check_message_read_status(message_id, headers, feishu_user_id)

        if not is_read:
            print(f"Message still unread, retrying urgent phone call (Retry {retry_count + 1})...")
            success = send_urgent_phone_call(message_id, headers, feishu_user_id)
            if not success:
                print(f"Urgent phone call retry {retry_count + 1} failed.")
            # 即使失败也继续尝试下一次，除非达到最大次数
        else:
            print("Message has been read, stopping urgent call retries.")
            break # 已读，跳出循环

        retry_count += 1

    if retry_count == max_retries and not is_read:
        print(f"Max retries ({max_retries}) reached, message still unread.")

def call_feishu(tweet, feishu_user_id, monitored_username): # 接受 feishu_user_id 和 monitored_username
    """发送飞书通知的主函数"""
    try:
        print(f"Starting Feishu notification process for @{monitored_username} to user {feishu_user_id}...")

        # 1. 获取 tenant_access_token
        tenant_token = get_tenant_access_token()
        if not tenant_token:
            print("Failed to get tenant_access_token, skipping Feishu notification.")
            return
            
        # 2. 构建消息内容
        message_content = build_message_content(tweet, monitored_username)
        
        # 3. 发送飞书消息
        message_id, headers = send_feishu_message(tenant_token, message_content, feishu_user_id)
        if not message_id or not headers:
            print("Failed to send initial Feishu message, skipping urgent calls.")
            return
            
        # 4. 发送电话加急
        success = send_urgent_phone_call(message_id, headers, feishu_user_id)
        if success:
            # 5. 重试发送电话加急
            retry_urgent_phone_call(message_id, headers, feishu_user_id)
        else:
            print("Initial urgent phone call failed.")

    except Exception as e:
        print(f"Feishu notification process failed: {e}")

    print(f"Feishu notification process finished for @{monitored_username}.")

# === Mock Latest Tweet (现在接受 username) ===
def mock_latest_tweet(username):
    # 可以根据 username 返回不同的模拟数据，或者保持通用
    timestamp = time.time()
    mock_id = str(int(timestamp * 1000))[-10:] # 简单的变化ID
    return {
        'id': '1917291637962858735',
        'url': 'https://x.com/sama/status/1917291637962858735',
        'text': "we started rolling back the latest update to GPT-4o last night, it's now 100% rolled back for free users and we'll update again when it's finished for paid users, hopefully later today, we're working on additional fixes to model personality and will share more in the coming days",
        'created_at': "2025-04-29 18:55:22+00:00"
    }

# === Helper: Check if current time is within monitoring hours ===
def is_within_monitoring_hours():
    """检查当前时间是否在监控时间范围内（太平洋时间早上7点到11点）"""
    # 获取太平洋时间
    pacific_tz = pytz.timezone('America/Los_Angeles')
    pacific_time = datetime.datetime.now(pacific_tz)
    
    # 获取当前小时
    current_hour = pacific_time.hour
    
    # 检查是否在监控时间范围内
    is_monitoring_time = MONITOR_START_HOUR <= current_hour < MONITOR_END_HOUR
    
    if is_monitoring_time:
        print(f"Current Pacific Time: {pacific_time.strftime('%Y-%m-%d %H:%M:%S %Z')} within monitoring hours ({MONITOR_START_HOUR}:00 - {MONITOR_END_HOUR}:00).")
    else:
        print(f"Current Pacific Time: {pacific_time.strftime('%Y-%m-%d %H:%M:%S %Z')} outside monitoring hours.")
    
    return is_monitoring_time

# === 新增: 保存通知历史记录 ===
def save_notification_history(email, username, tweet):
    """将已发送的通知记录保存到 Supabase"""
    try:
        if not supabase:
            print("Supabase client is not initialized. Cannot save notification history.")
            return False
            
        # 创建要插入的数据
        notification_data = {
            'email': email,
            'twitter_username': username,
            'tweet_id': tweet.get('id', ''),
            'tweet_url': tweet.get('url', ''),
            'tweet_text': tweet.get('text', ''),
            'tweet_created_at': tweet.get('created_at', ''),
            # notified_at 字段由数据库默认值设置
        }
        
        # 插入数据到 notification_history 表
        print(f"Saving notification history for tweet {tweet.get('id', '')} sent to {email}...")
        response = supabase.table(SUPABASE_HISTORY_TABLE).insert(notification_data).execute()
        
        if response.data:
            print("Notification history saved successfully.")
            return True
        else:
            print("Failed to save notification history.")
            return False
    except Exception as e:
        print(f"Error saving notification history: {e}")
        return False

# === Main ===
def main():
    global supabase # 确保可以使用全局 supabase 客户端

    if not supabase:
        print("Supabase client is not initialized. Exiting.")
        return

    try:
        # 检查当前时间是否在监控时间范围内
        if not is_within_monitoring_hours():
            print("Skipping execution due to time constraints.")
            return

        # 从环境变量获取通知目标
        recipient_email = os.environ.get('EMAIL_RECIPIENT')
        feishu_user_id = os.environ.get('FEISHU_USER_ID') # 可能为 None

        # 从环境变量获取并处理要监控的 Twitter 用户名
        twitter_usernames_str = os.environ.get('TWITTER_USERNAME')
        if not twitter_usernames_str:
            print("Error: TWITTER_USERNAME environment variable is not set.")
            return

        usernames_list = [name.strip() for name in twitter_usernames_str.split(',') if name.strip()]
        if not usernames_list:
            print("Error: TWITTER_USERNAME environment variable is set but contains no valid usernames.")
            return

        # --- 修改点：只取第一个用户名进行监控 ---
        username_to_monitor = usernames_list[0]
        print(f"Monitoring only the first Twitter username: @{username_to_monitor}")
        # -------------------------------------

        if not recipient_email:
            print("Warning: EMAIL_RECIPIENT environment variable is not set. Email notifications will be skipped.")

        # --- 修改点：移除循环，直接处理第一个用户 ---
        print(f"\n--- Processing @{username_to_monitor} ---")
        try:
            # 1. 从 Supabase 获取上次记录的 tweet ID
            last_known_id = None
            response = supabase.table(SUPABASE_TABLE).select("last_tweet_id").eq("twitter_username", username_to_monitor).execute()
            if response.data:
                last_known_id = response.data[0].get('last_tweet_id')
                print(f"Last known tweet ID from Supabase for @{username_to_monitor}: {last_known_id}")
            else:
                print(f"No previous tweet ID found in Supabase for @{username_to_monitor}. Will notify on first found tweet.")

            # 2. 获取最新的 tweet
            # latest = mock_latest_tweet(username_to_monitor) # 使用 Mock 数据
            latest = get_latest_tweet_api(username_to_monitor) # 使用真实 API

            if not latest:
                print(f"Could not fetch latest tweet for @{username_to_monitor}. Skipping.")
                # 在这种单用户模式下，可以直接返回或记录错误后结束
                return

            new_tweet_id = latest['id']
            print(f"Latest tweet ID fetched for @{username_to_monitor}: {new_tweet_id}")

            # 3. 比较 ID 并发送通知
            if new_tweet_id != last_known_id:
                print(f"New tweet detected for @{username_to_monitor}! URL: {latest['url']}")

                # 发送邮件通知 (如果配置了接收者)
                if recipient_email:
                    send_email(latest, recipient_email, username_to_monitor)
                else:
                    print("Skipping email notification as recipient email is not configured.")

                # 发送飞书通知 (如果配置了飞书用户ID)
                if feishu_user_id:
                    call_feishu(latest, feishu_user_id, username_to_monitor)
                else:
                    print("Skipping Feishu notification as Feishu user ID is not configured.")
                
                # 保存通知历史记录 (如果发送了通知)
                if recipient_email:
                    save_notification_history(recipient_email, username_to_monitor, latest)

                # 4. 更新 Supabase 中的 last_tweet_id
                try:
                    print(f"Updating last_tweet_id in Supabase for @{username_to_monitor} to {new_tweet_id}...")
                    upsert_data = {'twitter_username': username_to_monitor, 'last_tweet_id': new_tweet_id}
                    supabase.table(SUPABASE_TABLE).upsert(upsert_data).execute()
                    print("Supabase update successful.")
                except Exception as db_e:
                    print(f"Error updating Supabase for @{username_to_monitor}: {db_e}")
            else:
                print(f"No new tweet found for @{username_to_monitor}.")

        except Exception as user_e:
            print(f"An error occurred while processing @{username_to_monitor}: {user_e}")
            # 发生错误，记录日志

        # --- 修改点：移除循环后的 sleep ---
        # time.sleep(1) # 不再需要

        print("\nMonitoring cycle finished (processed only the first user).")

    except Exception as e:
        print(f"An unexpected error occurred in main execution: {e}")

if __name__ == '__main__':
    main()
