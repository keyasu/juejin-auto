import requests
import time
import json
import os
from datetime import datetime

# 全局配置
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Referer": "https://juejin.cn/",
    "Origin": "https://juejin.cn"
}
# 重试配置
RETRY_TIMES = 3
RETRY_INTERVAL = 60  # 重试间隔（秒）

class JueJinAutoCheckin:
    def __init__(self):
        # 从环境变量读取敏感信息（GitHub Secrets 注入）
        self.juejin_cookie = os.getenv("JUEJIN_COOKIE", "")
        self.feishu_token = os.getenv("FEISHU_TOKEN", "")
        # 掘金签到接口（最新稳定版）
        self.checkin_url = "https://api.juejin.cn/growth_api/v1/check_in"
        # 掘金用户信息接口（校验Cookie有效性）
        self.user_info_url = "https://api.juejin.cn/user_api/v1/user/get"

    def log(self, content):
        """日志记录"""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_str = f"[{now}] {content}"
        print(log_str)
        # 写入日志文件（GitHub Actions 可查看）
        with open("juejin_checkin_log.txt", "a", encoding="utf-8") as f:
            f.write(log_str + "\n")
        return log_str

    def send_feishu_notify(self, title, content):
        """飞书机器人通知"""
        if not self.feishu_token:
            self.log("飞书Token未配置，跳过通知")
            return
        # 飞书机器人接口
        url = f"https://open.feishu.cn/open-apis/bot/v2/hook/{self.feishu_token}"
        payload = {
            "msg_type": "text",
            "content": {
                "text": f"【掘金自动签到】{title}\n{content}"
            }
        }
        try:
            response = requests.post(
                url,
                headers={"Content-Type": "application/json"},
                data=json.dumps(payload),
                timeout=10
            )
            if response.status_code == 200:
                self.log("飞书通知发送成功")
            else:
                self.log(f"飞书通知发送失败：{response.text}")
        except Exception as e:
            self.log(f"飞书通知异常：{str(e)}")

    def request_with_retry(self, method, url, **kwargs):
        """带重试的请求封装"""
        for i in range(RETRY_TIMES):
            try:
                response = requests.request(
                    method,
                    url,
                    headers=HEADERS,
                    cookies=self._parse_cookie(),
                    timeout=30,
                    **kwargs
                )
                return response
            except requests.exceptions.RequestException as e:
                self.log(f"请求失败（第{i+1}次）：{str(e)}")
                if i < RETRY_TIMES - 1:
                    time.sleep(RETRY_INTERVAL)
        return None

    def _parse_cookie(self):
        """解析Cookie字符串为字典"""
        cookie_dict = {}
        if not self.juejin_cookie:
            return cookie_dict
        for item in self.juejin_cookie.split(";"):
            item = item.strip()
            if "=" in item:
                key, value = item.split("=", 1)
                cookie_dict[key] = value
        return cookie_dict

    def check_cookie_valid(self):
        """校验掘金Cookie是否有效"""
        self.log("开始校验掘金Cookie有效性")
        response = self.request_with_retry("GET", self.user_info_url)
        if not response:
            self.log("Cookie校验请求失败")
            return False
        if response.status_code == 200:
            result = response.json()
            if result.get("err_no") == 0:
                self.log(f"Cookie有效，当前用户：{result.get('data', {}).get('user_name', '未知')}")
                return True
            else:
                self.log(f"Cookie无效：{result.get('err_msg', '未知错误')}")
                return False
        else:
            self.log(f"Cookie校验失败，状态码：{response.status_code}")
            return False

    def juejin_checkin(self):
        """执行掘金签到"""
        self.log("===== 开始执行掘金签到 =====")
        # 第一步：校验Cookie
        if not self.check_cookie_valid():
            self.send_feishu_notify("签到失败", "Cookie无效/已过期，请重新导出更新")
            return False
        
        # 第二步：调用签到接口
        response = self.request_with_retry("POST", self.checkin_url)
        if not response:
            self.log("签到请求重试多次仍失败")
            self.send_feishu_notify("签到失败", "签到接口请求超时/异常，请手动签到")
            return False
        
        # 第三步：解析签到结果
        try:
            result = response.json()
        except json.JSONDecodeError:
            self.log(f"签到响应解析失败：{response.text}")
            self.send_feishu_notify("签到失败", f"接口响应异常：{response.text[:100]}")
            return False
        
        err_no = result.get("err_no", -1)
        if err_no == 0:
            # 签到成功
            incr_point = result.get("data", {}).get("incr_point", 0)
            total_point = result.get("data", {}).get("sum_point", 0)
            success_log = f"签到成功！获得矿石：{incr_point}，累计矿石：{total_point}"
            self.log(success_log)
            self.send_feishu_notify("签到成功", success_log)
            return True
        elif err_no == 165001:
            # 今日已签到
            self.log("今日已签到，无需重复操作")
            self.send_feishu_notify("已签到", "今日掘金已完成签到，无需重复操作")
            return True
        else:
            # 其他错误
            err_msg = result.get("err_msg", "未知错误")
            self.log(f"签到失败：{err_msg}（错误码：{err_no}）")
            self.send_feishu_notify("签到失败", f"错误原因：{err_msg}（错误码：{err_no}），请手动签到")
            return False

    def run(self):
        """执行主流程"""
        try:
            self.juejin_checkin()
        except Exception as e:
            self.log(f"签到流程异常：{str(e)}")
            self.send_feishu_notify("流程异常", f"签到脚本执行出错：{str(e)}")
        finally:
            self.log("===== 掘金签到流程结束 =====\n")

if __name__ == "__main__":
    checkin = JueJinAutoCheckin()
    checkin.run()
