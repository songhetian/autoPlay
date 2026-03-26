import cv2
import numpy as np
import pyautogui
import time
from PIL import ImageGrab

class ImageEngine:
    """图像识别与点击引擎"""

    @staticmethod
    def find_image_on_screen(template_path, threshold=0.8):
        """
        在屏幕上寻找目标图片
        :param template_path: 模板图片路径
        :param threshold: 相似度阈值
        :return: (x, y) 中心坐标，若未找到则返回 None
        """
        # 1. 截取当前屏幕
        screen = np.array(ImageGrab.grab())
        screen_gray = cv2.cvtColor(screen, cv2.COLOR_BGR2GRAY)
        
        # 2. 读取模板
        template = cv2.imread(template_path, 0)
        if template is None:
            return None
            
        w, h = template.shape[::-1]
        
        # 3. 模板匹配
        res = cv2.matchTemplate(screen_gray, template, cv2.TM_CCOEFF_NORMED)
        min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(res)
        
        if max_val >= threshold:
            # 返回中心点
            center_x = max_loc[0] + w // 2
            center_y = max_loc[1] + h // 2
            return (center_x, center_y)
        
        return None

    @staticmethod
    def click_image(template_path, threshold=0.8):
        """寻找并点击图片"""
        pos = ImageEngine.find_image_on_screen(template_path, threshold)
        if pos:
            pyautogui.click(pos[0], pos[1])
            return True
        return False

    @staticmethod
    def wait_for_image(template_path, timeout=10, threshold=0.8):
        """等待图片出现"""
        start_time = time.time()
        while time.time() - start_time < timeout:
            pos = ImageEngine.find_image_on_screen(template_path, threshold)
            if pos:
                return pos
            time.sleep(0.5)
        return None
