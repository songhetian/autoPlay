import time
import pyautogui
from core.image_engine import ImageEngine

class AutomationRunner:
    def __init__(self, invoice_map, workflow_steps, logger_func):
        """
        :param invoice_map: {订单号: 路径}
        :param workflow_steps: 用户定义的动作列表
        :param logger_func: 用于输出日志的回调函数
        """
        self.invoice_map = invoice_map
        self.workflow_steps = workflow_steps
        self.log = logger_func
        self.is_running = True

    def run(self):
        self.log(f"开始执行自动化，共 {len(self.invoice_map)} 笔订单", "#61afef")
        
        for order_no, file_path in self.invoice_map.items():
            if not self.is_running: break
            
            self.log(f"▶ 正在处理订单: {order_no}")
            
            try:
                for step in self.workflow_steps:
                    action = step['action']
                    
                    if action == "点击图片 (找图)":
                        # 实际开发中需从图片库获取路径
                        self.log(f"  - 寻找图片并点击...")
                        # ImageEngine.click_image("assets/btn.png")
                        
                    elif action == "输入文字 (订单号)":
                        self.log(f"  - 输入订单号: {order_no}")
                        pyautogui.write(order_no)
                        
                    elif action == "上传文件 (PDF)":
                        self.log(f"  - 模拟上传文件: {os.path.basename(file_path)}")
                        pyautogui.write(file_path)
                        pyautogui.press('enter')
                        
                    elif action == "等待 (秒)":
                        duration = step.get('value', 2)
                        self.log(f"  - 等待 {duration} 秒...")
                        time.sleep(duration)
                        
                    elif action == "按下回车":
                        pyautogui.press('enter')

                self.log(f"✔ 订单 {order_no} 处理指令已发送", "#98c379")
                
            except Exception as e:
                self.log(f"❌ 订单 {order_no} 执行出错: {str(e)}", "#e06c75")
                
        self.log("🏁 所有任务执行完毕", "#98c379")

    def stop(self):
        self.is_running = False
