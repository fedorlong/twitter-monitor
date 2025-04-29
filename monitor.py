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

# === Load .env ===
load_dotenv()

# === Config ===
TWITTER_USERNAME = os.environ['TWITTER_USERNAME']
LAST_TWEET_FILE = 'last_tweet.json'
# 设置监控时间范围（太平洋时间）
MONITOR_START_HOUR = 7  # 早上7点开始
MONITOR_END_HOUR = 11   # 早上11点结束

# === Helper: Get Latest Tweet (使用Twitter API) ===
def get_latest_tweet_api():
    try:
        import tweepy
        
        # Twitter API凭据
        api_key = os.environ.get('TWITTER_API_KEY')
        api_secret = os.environ.get('TWITTER_API_SECRET')
        access_token = os.environ.get('TWITTER_ACCESS_TOKEN')
        access_secret = os.environ.get('TWITTER_ACCESS_SECRET')
        bearer_token = os.environ.get('TWITTER_BEARER_TOKEN')
        
        # 检查是否有足够的凭据
        # OAuth 1.0a (用户认证)
        if all([api_key, api_secret, access_token, access_secret]):
            print("使用OAuth 1.0a认证方式...")
            auth = tweepy.OAuth1UserHandler(api_key, api_secret, access_token, access_secret)
            api = tweepy.API(auth)
            
            # 获取最新推文
            tweets = api.user_timeline(screen_name=TWITTER_USERNAME, count=1, tweet_mode="extended")
            if tweets:
                tweet = tweets[0]
                tweet_id = tweet.id_str
                tweet_url = f"https://x.com/{TWITTER_USERNAME}/status/{tweet_id}"
                tweet_text = tweet.full_text
                created_at = tweet.created_at
                print(f"成功获取到推文，发布时间: {created_at}")
                print(f"推文内容: {tweet_text[:50]}..." if len(tweet_text) > 50 else f"推文内容: {tweet_text}")
                return {'id': tweet_id, 'url': tweet_url, 'text': tweet_text, 'created_at': str(created_at)}
        
        # OAuth 2.0 (应用认证)
        elif bearer_token:
            print("使用OAuth 2.0 Bearer Token认证方式...")
            client = tweepy.Client(bearer_token=bearer_token)
            
            # 获取用户ID
            user = client.get_user(username=TWITTER_USERNAME)
            if not user or not user.data:
                print(f"无法获取用户 {TWITTER_USERNAME} 的信息")
                return None
                
            user_id = user.data.id
            
            # 获取用户最新推文
            tweets = client.get_users_tweets(
                id=user_id, 
                max_results=5,
                tweet_fields=['created_at', 'text']
            )
            
            if tweets and tweets.data:
                tweet = tweets.data[0]
                tweet_id = tweet.id
                tweet_url = f"https://x.com/{TWITTER_USERNAME}/status/{tweet_id}"
                tweet_text = tweet.text
                created_at = tweet.created_at
                print(f"成功获取到推文，发布时间: {created_at}")
                print(f"推文内容: {tweet_text[:50]}..." if len(tweet_text) > 50 else f"推文内容: {tweet_text}")
                return {'id': str(tweet_id), 'url': tweet_url, 'text': tweet_text, 'created_at': str(created_at)}
            else:
                print("未找到推文")
        else:
            print("缺少必要的Twitter API凭据")
            print("请在.env文件中设置以下环境变量之一组合:")
            print("选项1: TWITTER_API_KEY, TWITTER_API_SECRET, TWITTER_ACCESS_TOKEN, TWITTER_ACCESS_SECRET")
            print("选项2: TWITTER_BEARER_TOKEN")
            
        return None
    except Exception as e:
        print(f"Twitter API请求失败: {e}")
        return None

# === Helper: State ===
def load_last_id():
    if not os.path.exists(LAST_TWEET_FILE):
        return None
    with open(LAST_TWEET_FILE, 'r') as f:
        return json.load(f)['id']

def save_last_id(tweet_id):
    with open(LAST_TWEET_FILE, 'w') as f:
        json.dump({'id': tweet_id}, f)

# === Send Email ===
def send_email(tweet):
    smtp_server = 'smtp.gmail.com'
    smtp_port = 587
    sender = os.environ['EMAIL_SENDER']
    password = os.environ['EMAIL_PASSWORD']
    recipient = os.environ['EMAIL_RECIPIENT']

    subject = f"Twitter 更新通知：{TWITTER_USERNAME} 发新推文"
    
    # 构建邮件内容，包含更多信息
    if 'text' in tweet:
        body = f"""
发现新推文：

内容: {tweet['text']}

链接: {tweet['url']}

时间: {tweet.get('created_at', '未知')}
        """
    else:
        body = f"发现新推文：{tweet['url']}"

    msg = MIMEMultipart()
    msg['From'] = sender
    msg['To'] = recipient
    msg['Subject'] = Header(subject, 'utf-8')
    msg.attach(MIMEText(body, 'plain', 'utf-8'))

    server = smtplib.SMTP(smtp_server, smtp_port)
    server.starttls()
    server.login(sender, password)
    server.send_message(msg)
    server.quit()
    
    print(f"邮件已发送至 {recipient}")

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

def build_message_content(tweet):
    """构建飞书消息内容"""
    message_content = f"🔔 X(Twitter)更新提醒 🔔\n\n"
    message_content += f"用户: @{TWITTER_USERNAME}\n\n"
    
    if 'text' in tweet:
        message_content += f"内容: {tweet['text']}\n\n"
        
    if 'created_at' in tweet:
        message_content += f"时间: {tweet['created_at']}\n\n"
        
    message_content += f"链接: {tweet['url']}"
    return message_content

def send_feishu_message(tenant_token, message_content):
    """发送飞书消息并返回消息ID"""
    try:
        headers = {
            'Authorization': f'Bearer {tenant_token}',
            'Content-Type': 'application/json'
        }
        
        # 消息发送参数
        message_data = {
            "receive_id": os.environ['FEISHU_USER_ID'],
            "content": json.dumps({"text": message_content}),
            "msg_type": "text"
        }
        
        # 发送消息
        send_url = "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=user_id"
        send_response = requests.post(send_url, headers=headers, json=message_data)
        send_result = send_response.json()
        
        print(f"飞书消息发送结果: 状态码={send_response.status_code}, 响应={send_result}")
        
        # 检查消息是否发送成功
        if send_result.get('code') == 0 and 'data' in send_result and 'message_id' in send_result['data']:
            message_id = send_result['data']['message_id']
            print(f"消息发送成功，message_id: {message_id}")
            return message_id, headers
        else:
            print(f"发送消息失败: {send_result.get('msg', '未知错误')}")
            return None, None
    except Exception as e:
        print(f"发送飞书消息时出错: {e}")
        return None, None

def send_urgent_phone_call(message_id, headers):
    """发送电话加急通知"""
    try:
        print("开始发送电话加急...")
        
        # 电话加急API
        urgent_url = f"https://open.feishu.cn/open-apis/im/v1/messages/{message_id}/urgent_phone?user_id_type=user_id"
        
        # 电话加急参数
        urgent_data = {
            "user_id_list": [os.environ['FEISHU_USER_ID']]
        }
        
        # 发送电话加急请求
        urgent_response = requests.patch(urgent_url, headers=headers, json=urgent_data)
        
        # 解析响应
        if urgent_response.text.strip():
            urgent_result = urgent_response.json()
            
            if urgent_result.get('code') == 0:
                print("电话加急发送成功!")
                return True
            else:
                error_code = urgent_result.get('code')
                error_msg = urgent_result.get('msg', '未知错误')
                print(f"电话加急发送失败: code={error_code}, msg={error_msg}")
                return False
    except Exception as e:
        print(f"发送电话加急时出错: {e}")
        return False

def check_message_read_status(message_id, headers):
    """检查消息是否已读"""
    try:
        # 使用正确的消息已读信息接口
        status_url = f"https://open.feishu.cn/open-apis/im/v1/messages/{message_id}/read_users?user_id_type=user_id"
        status_response = requests.get(status_url, headers=headers)
        status_result = status_response.json()
        
        if status_result.get('code') == 0:
            # 根据飞书API文档，响应结构为：
            # {
            #   "code": 0,
            #   "data": {
            #     "has_more": false,
            #     "items": [
            #       {
            #         "tenant_key": "126c64334e8fd75e",
            #         "timestamp": "1745832642000",
            #         "user_id": "c7f62292",
            #         "user_id_type": "user_id"
            #       }
            #     ]
            #   },
            #   "msg": "success"
            # }
            
            # 获取已读用户列表
            read_users = status_result.get('data', {}).get('items', [])
            
            # 简化逻辑：只要items数组长度大于0就表示已读
            is_read = len(read_users) > 0
            
            if is_read:
                # 获取第一个已读用户的时间戳
                read_time = read_users[0].get('timestamp')
                if read_time:
                    # 将时间戳转换为可读格式
                    read_time_ms = int(read_time)
                    read_time_sec = read_time_ms / 1000
                    read_time_str = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(read_time_sec))
                    print(f"消息已被读取，读取时间: {read_time_str}")
                else:
                    print("消息已被读取")
            else:
                print("消息未被读取")
                
            return is_read
        else:
            error_code = status_result.get('code')
            error_msg = status_result.get('msg', '未知错误')
            print(f"检查消息状态失败: code={error_code}, msg={error_msg}")
            return False
    except Exception as e:
        print(f"检查消息状态时出错: {e}")
        return False

def retry_urgent_phone_call(message_id, headers, max_retries=2, wait_seconds=90):
    """重试发送电话加急通知"""
    retry_count = 0
    
    while retry_count < max_retries:
        # 等待指定时间
        print(f"等待{wait_seconds}秒后检查消息状态...")
        time.sleep(wait_seconds)
        
        # 检查消息状态
        is_read = check_message_read_status(message_id, headers)
        
        if not is_read:
            print(f"消息仍未读，第{retry_count+1}次重试发送电话加急...")
            
            # 再次发送电话加急
            success = send_urgent_phone_call(message_id, headers)
            if not success:
                print(f"第{retry_count+1}次电话加急发送失败")
        else:
            print("消息已被读取，无需再次发送电话加急")
            break
            
        retry_count += 1
    
    if retry_count == max_retries and not is_read:
        print(f"已达到最大重试次数({max_retries})，停止重试")

def call_feishu(tweet):
    """发送飞书通知的主函数"""
    try:
        print("开始发送飞书通知...")
        
        # 1. 获取 tenant_access_token
        tenant_token = get_tenant_access_token()
        if not tenant_token:
            return
            
        # 2. 构建消息内容
        message_content = build_message_content(tweet)
        
        # 3. 发送飞书消息
        message_id, headers = send_feishu_message(tenant_token, message_content)
        if not message_id or not headers:
            return
            
        # 4. 发送电话加急
        success = send_urgent_phone_call(message_id, headers)
        if success:
            # 5. 重试发送电话加急
            retry_urgent_phone_call(message_id, headers)
            
    except Exception as e:
        print(f"飞书通知发送失败: {e}")
        
    print("飞书通知处理完成")

# === Mock Latest Tweet ===
def mock_latest_tweet():
    return {
        'id': '1915121671251620265',
        'url': 'https://x.com/sama/status/1915121671251620265',
        'text': '@SelfMadeMastery super happy to hear it was helpfu... 他又发新的内容了', 
        'created_at': '2025-04-23 19:12:42+00:00'
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
        print(f"当前太平洋时间: {pacific_time.strftime('%Y-%m-%d %H:%M:%S %Z')}，在监控时间范围内")
    else:
        print(f"当前太平洋时间: {pacific_time.strftime('%Y-%m-%d %H:%M:%S %Z')}，不在监控时间范围内")
    
    return is_monitoring_time

# === Main ===
def main():
    try:
        # 检查当前时间是否在监控时间范围内
        if not is_within_monitoring_hours():
            print("当前时间不在监控时间范围内，跳过执行")
            return
            
        # 只使用Twitter API
        latest = get_latest_tweet_api()
        # latest = mock_latest_tweet()
        
        if not latest:
            print("无法通过Twitter API获取推文信息")
            return
            
        last_id = load_last_id()
        # 修复判断条件，当ID不同（有新推文）时才发送通知
        if latest['id'] != last_id:
            print(f"检测到新推文：{latest['url']}")
            
            # 取消注释下面的行来启用邮件和飞书通知
            send_email(latest)
            call_feishu(latest)
            
            save_last_id(latest['id'])
        else:
            print("无新推文")
    except Exception as e:
        print(f"出错：{e}")

if __name__ == '__main__':
    main()
