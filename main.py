import datetime
import json
import os
import pyautogui
import shutil
import sys
import threading

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.parser import InvoiceParser
from core.browser_manager import BrowserManager
from core.image_engine import ImageEngine


STEP_TEMPLATES = [
    {"type": "open_browser", "title": "打开网页", "category": "启动", "description": "打开浏览器并进入上传页面", "config": {"url": ""}},
    {"type": "refresh_page", "title": "刷新页面", "category": "启动", "description": "刷新当前网页", "config": {}},
    {"type": "click_element", "title": "点击元素", "category": "网页操作", "description": "点击元素库中的控件", "config": {"target": ""}},
    {"type": "double_click_element", "title": "双击元素", "category": "网页操作", "description": "双击元素库中的控件", "config": {"target": ""}},
    {"type": "focus_element", "title": "聚焦元素", "category": "网页操作", "description": "把焦点切到指定输入框", "config": {"target": ""}},
    {"type": "wait_element", "title": "等待元素出现", "category": "网页操作", "description": "等页面控件加载出来", "config": {"target": "", "timeout": 10}},
    {"type": "click_image", "title": "点击图片", "category": "图像操作", "description": "通过图片识别兜底点击", "config": {"target": "", "threshold": 90}},
    {"type": "wait_image", "title": "等待图片出现", "category": "图像操作", "description": "等待图片库中的标志出现", "config": {"target": "", "threshold": 90, "timeout": 10}},
    {"type": "input_order_no", "title": "输入订单号", "category": "变量输入", "description": "自动写入解析出的订单号", "config": {"target": "", "binding": "{{current.order_no}}"}},
    {"type": "input_file_name", "title": "输入文件名", "category": "变量输入", "description": "自动写入解析出的文件名", "config": {"target": "", "binding": "{{current.file_name}}"}},
    {"type": "input_file_path", "title": "输入文件路径", "category": "变量输入", "description": "自动写入解析出的完整文件路径", "config": {"target": "", "binding": "{{current.file_path}}"}},
    {"type": "input_fixed_text", "title": "输入固定内容", "category": "变量输入", "description": "输入手工填写的固定文本", "config": {"target": "", "text": ""}},
    {"type": "upload_file", "title": "上传文件", "category": "文件操作", "description": "优先向网页上传控件写入当前发票路径，找不到时再回退到 Windows 文件框", "config": {"target": "", "binding": "{{current.file_path}}"}},
    {"type": "delete_current_file", "title": "删除当前文件", "category": "文件操作", "description": "上传成功后删除当前发票文件", "config": {}},
    {"type": "wait", "title": "固定等待", "category": "流程控制", "description": "固定等待若干秒", "config": {"seconds": 2}},
    {"type": "press_enter", "title": "按回车", "category": "流程控制", "description": "向当前焦点发送 Enter", "config": {}},
    {"type": "press_tab", "title": "按 Tab", "category": "流程控制", "description": "切换到下一个输入位置", "config": {}},
    {"type": "screenshot", "title": "截图留档", "category": "辅助", "description": "保存当前界面的截图", "config": {"name": "上传结果截图"}},
    {"type": "log", "title": "写日志", "category": "辅助", "description": "在运行时输出一条日志", "config": {"message": "进入下一步"}},
]

STEP_TEMPLATE_MAP = {item["type"]: item for item in STEP_TEMPLATES}


class DropZone(QFrame):
    clicked = Signal()
    folder_dropped = Signal(str)

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setObjectName("DropZone")
        self.setFixedHeight(108)
        self.setStyleSheet(
            """
            #DropZone {
                border: 2px dashed #94a3b8;
                border-radius: 8px;
                background: #f8fafc;
            }
            #DropZone:hover {
                background: #f1f5f9;
            }
            """
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 12, 18, 12)
        layout.setSpacing(14)

        icon = QLabel("PDF")
        icon.setAlignment(Qt.AlignCenter)
        icon.setFixedSize(54, 54)
        icon.setStyleSheet(
            "background:#1f2937;color:white;font-size:16px;font-weight:700;border-radius:8px;"
        )
        layout.addWidget(icon)

        self.text_label = QLabel("拖入发票文件夹，或点击选择目录")
        self.text_label.setStyleSheet("font-size:14px;font-weight:600;color:#293241;")
        layout.addWidget(self.text_label, 1)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        urls = event.mimeData().urls()
        if not urls:
            return
        path = urls[0].toLocalFile()
        if os.path.isdir(path):
            self.folder_dropped.emit(path)


class LibraryList(QListWidget):
    item_activated_signal = Signal(str)

    def __init__(self):
        super().__init__()
        self.setSpacing(6)
        self.itemDoubleClicked.connect(self._emit_item)
        self.itemClicked.connect(self._emit_item)

    def _emit_item(self, item):
        key = item.data(Qt.UserRole)
        if key:
            self.item_activated_signal.emit(key)


class WorkflowList(QListWidget):
    step_selected = Signal(int)

    def __init__(self):
        super().__init__()
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setSpacing(10)
        self.currentRowChanged.connect(self.step_selected.emit)


class ElementEditorDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("新增页面元素")
        self.resize(620, 420)

        layout = QVBoxLayout(self)
        intro = QLabel("CSS 和 XPath 的定位最准确。这里保留专业定位方式，但把录入说明做直观一些。")
        intro.setWordWrap(True)
        intro.setStyleSheet("color:#5b6472;")
        layout.addWidget(intro)

        form = QFormLayout()
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("例如：订单号输入框 / 查询按钮 / 上传确认按钮")
        form.addRow("元素名称", self.name_edit)

        self.role_combo = QComboBox()
        self.role_combo.addItems(["输入框", "按钮", "上传入口", "查询入口", "确认按钮", "页面标签", "弹窗", "其他"])
        form.addRow("元素用途", self.role_combo)

        self.area_edit = QLineEdit()
        self.area_edit.setPlaceholderText("例如：页面上方查询区 / 上传弹窗右下角")
        form.addRow("页面位置说明", self.area_edit)

        self.locator_combo = QComboBox()
        self.locator_combo.addItems(["CSS 选择器", "XPath", "文本匹配", "ID", "Name"])
        form.addRow("定位方式", self.locator_combo)

        self.locator_edit = QTextEdit()
        self.locator_edit.setPlaceholderText(
            "例如：\nCSS：input[placeholder='请输入订单号']\nXPath：//button[contains(., '查询')]"
        )
        self.locator_edit.setFixedHeight(100)
        form.addRow("定位表达式", self.locator_edit)

        self.note_edit = QTextEdit()
        self.note_edit.setPlaceholderText("写给自己看的备注，例如“用于输入订单号，点击查询前填写”")
        self.note_edit.setFixedHeight(72)
        form.addRow("使用说明", self.note_edit)
        layout.addLayout(form)

        quick_group = QGroupBox("常用模板")
        quick_layout = QGridLayout(quick_group)
        quick_templates = [
            ("订单号输入框", "输入框", "页面上方查询区", "CSS 选择器", "input[placeholder*='订单']", "处理每个订单前先写入订单号"),
            ("查询按钮", "查询入口", "订单号输入框右侧", "XPath", "//button[contains(., '查询')]", "输入订单号后点击"),
            ("上传发票按钮", "上传入口", "订单详情区", "XPath", "//button[contains(., '上传')]", "打开文件选择框"),
            ("上传确认按钮", "确认按钮", "上传弹窗右下角", "XPath", "//button[contains(., '确认')]", "文件选好后点击确认"),
        ]
        for index, preset in enumerate(quick_templates):
            button = QPushButton(preset[0])
            button.clicked.connect(lambda _, p=preset: self.apply_template(p))
            quick_layout.addWidget(button, index // 2, index % 2)
        layout.addWidget(quick_group)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def apply_template(self, preset):
        name, role, area, locator_kind, locator_value, note = preset
        self.name_edit.setText(name)
        self.role_combo.setCurrentText(role)
        self.area_edit.setText(area)
        self.locator_combo.setCurrentText(locator_kind)
        self.locator_edit.setPlainText(locator_value)
        self.note_edit.setPlainText(note)

    def get_data(self):
        return {
            "name": self.name_edit.text().strip(),
            "element_role": self.role_combo.currentText().strip(),
            "locator_type": self.locator_combo.currentText().strip(),
            "locator_value": self.locator_edit.toPlainText().strip(),
            "area": self.area_edit.text().strip(),
            "note": self.note_edit.toPlainText().strip(),
            "status": "已录入",
        }


class RPAMainWindow(QMainWindow):
    element_picked_signal = Signal(dict)
    browser_status_signal = Signal(str)

    def __init__(self):
        super().__init__()
        self.base_dir = os.path.abspath(os.path.dirname(__file__))
        self.data_dir = os.path.join(self.base_dir, "data")
        self.scheme_store_path = os.path.join(self.data_dir, "schemes.json")
        self.browser_profile_root = os.path.join(self.data_dir, "browser_profiles")
        os.makedirs(self.browser_profile_root, exist_ok=True)

        self.invoice_dir = ""
        self.invoice_map = {}
        self.invoice_rows = []
        self.latest_excel_path = ""
        self.workflow_steps = []
        self.elements = []
        self.images = []
        self.current_step_index = -1
        self.order_statuses = {}
        self.order_index_map = {}
        self.browser_manager = None
        self.capture_thread = None
        self.capture_context = None
        self.capture_default_url = "https://example.com"
        self.schemes = self.load_json(self.scheme_store_path, [])
        self.current_scheme_name = ""
        self.scheme_switching = False

        if not self.schemes:
            self.schemes = [self.build_scheme_payload("默认方案")]
        self.current_scheme_name = self.schemes[0]["name"]

        self.element_picked_signal.connect(self.handle_picked_element)
        self.browser_status_signal.connect(self.handle_browser_status)

        self.setWindowTitle("发票自动上传工作台")
        self.resize(1480, 920)
        self.setMinimumSize(1180, 760)
        self.init_ui()
        self.refresh_element_library()
        self.refresh_image_library()
        self.refresh_step_library()
        self.refresh_workflow_view()
        self.refresh_parsed_table()
        self.refresh_scheme_combo()
        self.apply_scheme_by_name(self.current_scheme_name)

    def init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        header = QFrame()
        header.setStyleSheet("background:#ffffff;border:1px solid #d1d5db;border-radius:8px;")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(18, 16, 18, 16)
        title = QLabel("可视化 RPA 发票上传")
        title.setStyleSheet("font-size:22px;font-weight:700;color:#1f2937;")
        subtitle = QLabel("节点库 + 流程画布 + 属性面板，输入值直接绑定文件夹解析结果")
        subtitle.setStyleSheet("font-size:13px;color:#64748b;")
        header_layout.addWidget(title)
        header_layout.addWidget(subtitle)
        scheme_row = QHBoxLayout()
        scheme_row.addWidget(QLabel("方案"))
        self.scheme_combo = QComboBox()
        self.scheme_combo.currentTextChanged.connect(self.on_scheme_changed)
        scheme_row.addWidget(self.scheme_combo, 1)
        new_scheme_btn = QPushButton("新建方案")
        new_scheme_btn.clicked.connect(self.create_new_scheme)
        save_scheme_btn = QPushButton("保存方案")
        save_scheme_btn.clicked.connect(self.save_current_scheme)
        delete_scheme_btn = QPushButton("删除方案")
        delete_scheme_btn.clicked.connect(self.delete_current_scheme)
        scheme_row.addWidget(new_scheme_btn)
        scheme_row.addWidget(save_scheme_btn)
        scheme_row.addWidget(delete_scheme_btn)
        header_layout.addLayout(scheme_row)
        root.addWidget(header)

        source_group = QGroupBox("数据源")
        source_layout = QVBoxLayout(source_group)
        self.drop_zone = DropZone()
        self.drop_zone.clicked.connect(self.on_select_invoice_dir)
        self.drop_zone.folder_dropped.connect(self.set_invoice_dir)
        source_layout.addWidget(self.drop_zone)

        row = QHBoxLayout()
        self.export_path_edit = QLineEdit(os.path.join(os.path.expanduser("~"), "Desktop"))
        self.export_path_edit.setPlaceholderText("Excel 输出目录")
        row.addWidget(QLabel("导出目录"))
        row.addWidget(self.export_path_edit, 1)

        change_btn = QPushButton("更改")
        change_btn.clicked.connect(self.on_select_export_dir)
        row.addWidget(change_btn)

        self.summary_label = QLabel("未加载文件夹")
        self.summary_label.setStyleSheet("color:#475569;font-weight:600;")
        row.addWidget(self.summary_label)
        source_layout.addLayout(row)
        root.addWidget(source_group)

        main_splitter = QSplitter(Qt.Horizontal)
        root.addWidget(main_splitter, 1)

        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(12)
        library_tabs = QTabWidget()
        left_layout.addWidget(library_tabs)

        step_tab = QWidget()
        step_library_layout = QVBoxLayout(step_tab)
        preset_row = QGridLayout()
        quick_flow_a = QPushButton("基础上传流程")
        quick_flow_a.clicked.connect(lambda: self.add_flow_preset("basic_upload"))
        quick_flow_b = QPushButton("查询后上传")
        quick_flow_b.clicked.connect(lambda: self.add_flow_preset("query_then_upload"))
        quick_flow_c = QPushButton("图片兜底流程")
        quick_flow_c.clicked.connect(lambda: self.add_flow_preset("image_fallback"))
        preset_row.addWidget(quick_flow_a, 0, 0)
        preset_row.addWidget(quick_flow_b, 0, 1)
        preset_row.addWidget(quick_flow_c, 1, 0, 1, 2)
        step_library_layout.addLayout(preset_row)
        self.step_library = LibraryList()
        self.step_library.item_activated_signal.connect(self.add_step_from_library)
        step_library_layout.addWidget(QLabel("双击节点加入流程，或先点上面的常用流程模板"))
        step_library_layout.addWidget(self.step_library)
        library_tabs.addTab(step_tab, "节点库")

        element_tab = QWidget()
        element_layout = QVBoxLayout(element_tab)
        element_btn_row = QHBoxLayout()
        add_element_btn = QPushButton("新增元素")
        add_element_btn.clicked.connect(self.add_element)
        capture_element_btn = QPushButton("智能获取元素")
        capture_element_btn.clicked.connect(self.capture_element)
        batch_element_btn = QPushButton("生成常用元素")
        batch_element_btn.clicked.connect(self.add_common_elements)
        remove_element_btn = QPushButton("删除元素")
        remove_element_btn.clicked.connect(self.remove_selected_element)
        element_btn_row.addWidget(add_element_btn)
        element_btn_row.addWidget(capture_element_btn)
        element_btn_row.addWidget(batch_element_btn)
        element_btn_row.addWidget(remove_element_btn)
        self.element_library = LibraryList()
        self.element_library.item_activated_signal.connect(self.bind_selected_element)
        element_layout.addWidget(QLabel("元素建议用 CSS / XPath 保存，点击条目可直接绑定到当前节点"))
        element_io_row = QHBoxLayout()
        import_elements_btn = QPushButton("导入元素库")
        import_elements_btn.clicked.connect(self.import_element_library)
        export_elements_btn = QPushButton("导出元素库")
        export_elements_btn.clicked.connect(self.export_element_library)
        element_io_row.addWidget(import_elements_btn)
        element_io_row.addWidget(export_elements_btn)
        login_row = QHBoxLayout()
        login_browser_btn = QPushButton("打开登录浏览器")
        login_browser_btn.clicked.connect(self.open_login_browser)
        test_locator_btn = QPushButton("测试元素定位")
        test_locator_btn.clicked.connect(self.test_selected_element)
        clear_login_btn = QPushButton("清除登录状态")
        clear_login_btn.clicked.connect(self.clear_scheme_login_state)
        login_row.addWidget(login_browser_btn)
        login_row.addWidget(test_locator_btn)
        login_row.addWidget(clear_login_btn)
        element_layout.addLayout(element_btn_row)
        element_layout.addLayout(element_io_row)
        element_layout.addLayout(login_row)
        element_layout.addWidget(self.element_library)
        library_tabs.addTab(element_tab, "元素库")

        image_tab = QWidget()
        image_layout = QVBoxLayout(image_tab)
        image_btn_row = QHBoxLayout()
        import_image_btn = QPushButton("导入图片")
        import_image_btn.clicked.connect(self.import_image)
        remove_image_btn = QPushButton("删除图片")
        remove_image_btn.clicked.connect(self.remove_selected_image)
        image_btn_row.addWidget(import_image_btn)
        image_btn_row.addWidget(remove_image_btn)
        self.image_library = LibraryList()
        self.image_library.item_activated_signal.connect(self.bind_selected_image)
        image_layout.addWidget(QLabel("用于页面元素失效时的图片兜底定位"))
        image_io_row = QHBoxLayout()
        import_images_btn = QPushButton("导入图片库")
        import_images_btn.clicked.connect(self.import_image_library)
        export_images_btn = QPushButton("导出图片库")
        export_images_btn.clicked.connect(self.export_image_library)
        image_io_row.addWidget(import_images_btn)
        image_io_row.addWidget(export_images_btn)
        image_layout.addLayout(image_btn_row)
        image_layout.addLayout(image_io_row)
        image_layout.addWidget(self.image_library)
        library_tabs.addTab(image_tab, "图片库")

        center_panel = QWidget()
        center_layout = QVBoxLayout(center_panel)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(12)

        canvas_group = QGroupBox("流程画布")
        canvas_layout = QVBoxLayout(canvas_group)
        hint = QLabel("参考影刀式线性节点流：拖动排序，点击节点在右侧编辑参数。")
        hint.setStyleSheet("color:#64748b;")
        canvas_layout.addWidget(hint)
        self.workflow_status_label = QLabel("流程统计：共 0 个节点，已配置 0 个，待配置 0 个，前台节点 0 个")
        self.workflow_status_label.setWordWrap(True)
        self.workflow_status_label.setStyleSheet("color:#475569;background:#f8fafc;padding:8px 10px;border-radius:8px;")
        canvas_layout.addWidget(self.workflow_status_label)

        canvas_btn_row = QHBoxLayout()
        clear_flow_btn = QPushButton("清空流程")
        clear_flow_btn.clicked.connect(self.clear_workflow)
        remove_step_btn = QPushButton("删除当前节点")
        remove_step_btn.clicked.connect(self.remove_step)
        move_up_btn = QPushButton("上移")
        move_up_btn.clicked.connect(lambda: self.move_step(-1))
        move_down_btn = QPushButton("下移")
        move_down_btn.clicked.connect(lambda: self.move_step(1))
        inspect_flow_btn = QPushButton("流程体检")
        inspect_flow_btn.clicked.connect(self.inspect_workflow)
        verify_upload_btn = QPushButton("批量验证上传")
        verify_upload_btn.clicked.connect(self.verify_all_upload_steps)
        canvas_btn_row.addWidget(clear_flow_btn)
        canvas_btn_row.addWidget(remove_step_btn)
        canvas_btn_row.addWidget(move_up_btn)
        canvas_btn_row.addWidget(move_down_btn)
        canvas_btn_row.addWidget(inspect_flow_btn)
        canvas_btn_row.addWidget(verify_upload_btn)
        test_step_btn = QPushButton("测试当前节点")
        test_step_btn.clicked.connect(self.test_current_step)
        canvas_btn_row.addWidget(test_step_btn)
        canvas_btn_row.addStretch()
        canvas_layout.addLayout(canvas_btn_row)

        self.workflow_list = WorkflowList()
        self.workflow_list.step_selected.connect(self.on_step_selected)
        canvas_layout.addWidget(self.workflow_list, 1)
        center_layout.addWidget(canvas_group, 3)

        parsed_group = QGroupBox("文件夹解析结果")
        parsed_layout = QVBoxLayout(parsed_group)
        token_row = QHBoxLayout()
        token_row.addWidget(self.make_token("订单号变量", "{{current.order_no}}"))
        token_row.addWidget(self.make_token("文件名变量", "{{current.file_name}}"))
        token_row.addWidget(self.make_token("文件路径变量", "{{current.file_path}}"))
        token_row.addStretch()
        parsed_layout.addLayout(token_row)

        self.parsed_table = QTableWidget(0, 3)
        self.parsed_table.setHorizontalHeaderLabels(["订单号", "文件名", "文件路径"])
        self.parsed_table.horizontalHeader().setStretchLastSection(True)
        self.parsed_table.verticalHeader().setVisible(False)
        self.parsed_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.parsed_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        parsed_layout.addWidget(self.parsed_table)
        center_layout.addWidget(parsed_group, 2)

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(12)

        property_group = QGroupBox("节点属性")
        self.property_layout = QVBoxLayout(property_group)
        self.property_layout.setContentsMargins(12, 12, 12, 12)
        self.property_hint = QLabel("选择一个流程节点后，在这里配置目标元素、图片和变量绑定。")
        self.property_hint.setWordWrap(True)
        self.property_hint.setStyleSheet("color:#64748b;")
        self.property_layout.addWidget(self.property_hint)
        right_layout.addWidget(property_group, 3)

        preview_group = QGroupBox("当前节点执行预览")
        preview_layout = QVBoxLayout(preview_group)
        self.preview_box = QTextEdit()
        self.preview_box.setReadOnly(True)
        self.preview_box.setMinimumHeight(120)
        preview_layout.addWidget(self.preview_box)
        right_layout.addWidget(preview_group, 1)

        run_group = QGroupBox("运行")
        run_layout = QVBoxLayout(run_group)
        retry_row = QHBoxLayout()
        retry_row.addWidget(QLabel("失败重试"))
        self.retry_spin = QSpinBox()
        self.retry_spin.setRange(1, 5)
        self.retry_spin.setValue(1)
        retry_row.addWidget(self.retry_spin)
        retry_row.addStretch()
        run_layout.addLayout(retry_row)
        stats_row = QHBoxLayout()
        self.total_stat_label = QLabel("总数 0")
        self.success_stat_label = QLabel("成功 0")
        self.failed_stat_label = QLabel("失败 0")
        stats_row.addWidget(self.total_stat_label)
        stats_row.addWidget(self.success_stat_label)
        stats_row.addWidget(self.failed_stat_label)
        stats_row.addStretch()
        run_layout.addLayout(stats_row)
        self.order_table = QTableWidget(0, 3)
        self.order_table.setHorizontalHeaderLabels(["订单号", "状态", "详情"])
        self.order_table.horizontalHeader().setStretchLastSection(True)
        self.order_table.verticalHeader().setVisible(False)
        self.order_table.setMinimumHeight(180)
        run_layout.addWidget(self.order_table)
        run_btn_row = QHBoxLayout()
        self.parse_only_btn = QPushButton("仅解析并导出 Excel")
        self.parse_only_btn.clicked.connect(self.run_parsing_only)
        self.run_btn = QPushButton("开始批量执行")
        self.run_btn.clicked.connect(self.start_automation)
        self.run_btn.setStyleSheet(
            "background:#15803d;color:white;font-size:16px;font-weight:700;padding:10px;border-radius:6px;"
        )
        run_btn_row.addWidget(self.parse_only_btn)
        run_btn_row.addWidget(self.run_btn)
        run_layout.addLayout(run_btn_row)
        right_layout.addWidget(run_group)

        log_group = QGroupBox("日志")
        log_layout = QVBoxLayout(log_group)
        log_btn_row = QHBoxLayout()
        clear_log_btn = QPushButton("清空日志")
        clear_log_btn.clicked.connect(self.clear_log_view)
        copy_log_btn = QPushButton("复制日志")
        copy_log_btn.clicked.connect(self.copy_log_view)
        log_btn_row.addWidget(clear_log_btn)
        log_btn_row.addWidget(copy_log_btn)
        log_btn_row.addStretch()
        log_layout.addLayout(log_btn_row)
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setStyleSheet("background:#111827;color:#d1d5db;font-family:Consolas;")
        self.log_view.setMinimumHeight(180)
        log_layout.addWidget(self.log_view)
        right_layout.addWidget(log_group, 4)

        main_splitter.addWidget(left_panel)
        main_splitter.addWidget(center_panel)
        main_splitter.addWidget(right_panel)
        main_splitter.setSizes([300, 620, 520])

        self.setStyleSheet(
            """
            QWidget {
                font-size: 13px;
            }
            QMainWindow {
                background: #f3f4f6;
            }
            QGroupBox {
                font-weight: 700;
                border: 1px solid #d1d5db;
                border-radius: 8px;
                margin-top: 10px;
                background: #ffffff;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 4px;
            }
            QTabWidget::pane {
                border: 1px solid #d1d5db;
                background: #ffffff;
                border-radius: 8px;
                top: -1px;
            }
            QTabBar::tab {
                background: #e5e7eb;
                border: 1px solid #d1d5db;
                padding: 8px 14px;
                margin-right: 2px;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
            }
            QTabBar::tab:selected {
                background: #ffffff;
                color: #111827;
                font-weight: 700;
            }
            QListWidget, QTableWidget, QTextEdit, QLineEdit, QSpinBox {
                border: 1px solid #d1d5db;
                border-radius: 6px;
                background: #ffffff;
            }
            QListWidget::item {
                border: 1px solid #e5e7eb;
                border-radius: 6px;
                margin: 2px 0;
                padding: 7px;
            }
            QListWidget::item:selected {
                background: #eff6ff;
                border: 1px solid #2563eb;
                color: #111827;
            }
            QPushButton {
                border: 1px solid #cbd5e1;
                border-radius: 6px;
                background: #f9fafb;
                padding: 7px 12px;
                font-weight: 600;
            }
            QPushButton:hover {
                background: #f3f4f6;
            }
            """
        )

    def make_token(self, title, value):
        token = QLabel(f"{title}  {value}")
        token.setStyleSheet(
            "background:#eef2ff;color:#3730a3;padding:8px 10px;border-radius:10px;font-weight:600;"
        )
        return token

    def log(self, text, color="#d8e1f0"):
        now = datetime.datetime.now().strftime("%H:%M:%S")
        self.log_view.append(
            f'<span style="color:#64748b;">[{now}]</span> <span style="color:{color};">{text}</span>'
        )
        scrollbar = self.log_view.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def clear_log_view(self):
        self.log_view.clear()
        self.log("日志已清空。", "#94a3b8")

    def copy_log_view(self):
        QApplication.clipboard().setText(self.log_view.toPlainText())
        self.log("日志内容已复制到剪贴板。", "#94a3b8")

    def show_completion_message(self, title, message):
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Information)
        box.setWindowTitle(title)
        box.setText(message)
        box.setStandardButtons(QMessageBox.Ok)
        box.exec()

    def load_json(self, path, default):
        if not os.path.exists(path):
            return default
        try:
            with open(path, "r", encoding="utf-8") as file:
                return json.load(file)
        except Exception:
            return default

    def save_json(self, path, value):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as file:
            json.dump(value, file, ensure_ascii=False, indent=2)

    def update_run_stats(self, total=0, success=0, failed=0):
        self.total_stat_label.setText(f"总数 {total}")
        self.success_stat_label.setText(f"成功 {success}")
        self.failed_stat_label.setText(f"失败 {failed}")

    def refresh_order_table(self):
        self.order_statuses.clear()
        self.order_index_map.clear()
        self.order_table.setRowCount(len(self.invoice_rows))
        for idx, row in enumerate(self.invoice_rows):
            order_no = row["order_no"]
            self.order_index_map[order_no] = idx
            status_item = QTableWidgetItem("待执行")
            status_item.setTextAlignment(Qt.AlignCenter)
            self.order_table.setItem(idx, 0, QTableWidgetItem(order_no))
            self.order_table.setItem(idx, 1, status_item)
            self.order_table.setItem(idx, 2, QTableWidgetItem("尚未执行"))

    def update_order_table_row(self, order_no, status, detail):
        idx = self.order_index_map.get(order_no)
        if idx is None:
            return
        self.order_table.item(idx, 1).setText(status)
        self.order_table.item(idx, 2).setText(detail)

    def build_scheme_payload(self, name):
        return {
            "name": name,
            "invoice_dir": "",
            "export_dir": os.path.join(os.path.expanduser("~"), "Desktop"),
            "workflow_steps": [],
            "capture_url": "https://example.com",
            "retry_count": 1,
        }

    def get_scheme_profile_dir(self, scheme_name):
        safe_name = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in scheme_name)
        return os.path.join(self.browser_profile_root, safe_name or "default")

    def get_scheme_data_dir(self, scheme_name):
        safe_name = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in scheme_name)
        path = os.path.join(self.data_dir, "scheme_assets", safe_name or "default")
        os.makedirs(path, exist_ok=True)
        return path

    def get_scheme_element_store_path(self, scheme_name):
        return os.path.join(self.get_scheme_data_dir(scheme_name), "elements.json")

    def get_scheme_image_store_path(self, scheme_name):
        return os.path.join(self.get_scheme_data_dir(scheme_name), "images.json")

    def get_scheme_image_asset_dir(self, scheme_name):
        path = os.path.join(self.get_scheme_data_dir(scheme_name), "images")
        os.makedirs(path, exist_ok=True)
        return path

    def load_scheme_resources(self, scheme_name):
        self.elements = self.load_json(self.get_scheme_element_store_path(scheme_name), [])
        self.images = self.load_json(self.get_scheme_image_store_path(scheme_name), [])

    def import_element_library(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "导入元素库", "", "JSON (*.json)")
        if not file_path:
            return
        imported = self.load_json(file_path, [])
        if not isinstance(imported, list):
            QMessageBox.warning(self, "导入失败", "元素库文件格式不正确。")
            return
        self.elements = imported
        self.save_json(self.get_scheme_element_store_path(self.current_scheme_name), self.elements)
        self.refresh_element_library()
        self.log(f"已导入元素库：{file_path}", "#34d399")

    def export_element_library(self):
        file_path, _ = QFileDialog.getSaveFileName(self, "导出元素库", "elements.json", "JSON (*.json)")
        if not file_path:
            return
        self.save_json(file_path, self.elements)
        self.log(f"已导出元素库：{file_path}", "#34d399")

    def import_image_library(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "导入图片库", "", "JSON (*.json)")
        if not file_path:
            return
        imported = self.load_json(file_path, [])
        if not isinstance(imported, list):
            QMessageBox.warning(self, "导入失败", "图片库文件格式不正确。")
            return
        self.images = imported
        self.save_json(self.get_scheme_image_store_path(self.current_scheme_name), self.images)
        self.refresh_image_library()
        self.log(f"已导入图片库：{file_path}", "#34d399")

    def export_image_library(self):
        file_path, _ = QFileDialog.getSaveFileName(self, "导出图片库", "images.json", "JSON (*.json)")
        if not file_path:
            return
        self.save_json(file_path, self.images)
        self.log(f"已导出图片库：{file_path}", "#34d399")

    def refresh_scheme_combo(self):
        self.scheme_switching = True
        self.scheme_combo.clear()
        self.scheme_combo.addItems([scheme["name"] for scheme in self.schemes])
        if self.current_scheme_name:
            self.scheme_combo.setCurrentText(self.current_scheme_name)
        self.scheme_switching = False

    def collect_current_scheme_payload(self):
        payload = self.build_scheme_payload(self.current_scheme_name or "默认方案")
        payload["invoice_dir"] = self.invoice_dir
        payload["export_dir"] = self.export_path_edit.text().strip()
        payload["workflow_steps"] = json.loads(json.dumps(self.workflow_steps, ensure_ascii=False))
        payload["capture_url"] = getattr(self, "capture_default_url", "https://example.com")
        payload["retry_count"] = self.retry_spin.value()
        return payload

    def save_current_scheme(self):
        if not self.current_scheme_name:
            return
        payload = self.collect_current_scheme_payload()
        replaced = False
        for index, scheme in enumerate(self.schemes):
            if scheme["name"] == self.current_scheme_name:
                self.schemes[index] = payload
                replaced = True
                break
        if not replaced:
            self.schemes.append(payload)
        self.save_json(self.scheme_store_path, self.schemes)
        self.refresh_scheme_combo()
        self.log(f"方案已保存：{self.current_scheme_name}", "#34d399")

    def apply_scheme_by_name(self, scheme_name):
        scheme = next((item for item in self.schemes if item["name"] == scheme_name), None)
        if not scheme:
            return
        self.scheme_switching = True
        self.current_scheme_name = scheme["name"]
        self.load_scheme_resources(self.current_scheme_name)
        self.invoice_dir = scheme.get("invoice_dir", "")
        self.workflow_steps = scheme.get("workflow_steps", [])
        self.capture_default_url = scheme.get("capture_url", "https://example.com")
        self.retry_spin.setValue(int(scheme.get("retry_count", 1)))
        self.export_path_edit.setText(scheme.get("export_dir", os.path.join(os.path.expanduser("~"), "Desktop")))
        self.refresh_element_library()
        self.refresh_image_library()
        if self.invoice_dir:
            self.drop_zone.text_label.setText(f"已选择目录：{os.path.basename(self.invoice_dir)}")
            self.parse_invoice_directory(auto_export=False)
        else:
            self.drop_zone.text_label.setText("拖入发票文件夹，或点击选择目录")
            self.invoice_map = {}
            self.invoice_rows = []
            self.refresh_parsed_table()
            self.summary_label.setText("未加载文件夹")
        self.refresh_workflow_view()
        self.scheme_combo.setCurrentText(self.current_scheme_name)
        self.scheme_switching = False

    def on_scheme_changed(self, scheme_name):
        if self.scheme_switching or not scheme_name or scheme_name == self.current_scheme_name:
            return
        self.save_current_scheme()
        self.apply_scheme_by_name(scheme_name)
        self.log(f"已切换方案：{scheme_name}", "#60a5fa")

    def create_new_scheme(self):
        name, ok = QInputDialog.getText(self, "新建方案", "方案名称")
        if not ok or not name.strip():
            return
        name = name.strip()
        if any(item["name"] == name for item in self.schemes):
            QMessageBox.warning(self, "方案已存在", "请换一个方案名称。")
            return
        self.save_current_scheme()
        self.schemes.append(self.build_scheme_payload(name))
        self.current_scheme_name = name
        self.save_json(self.scheme_store_path, self.schemes)
        self.refresh_scheme_combo()
        self.apply_scheme_by_name(name)
        self.log(f"已新建方案：{name}", "#34d399")

    def delete_current_scheme(self):
        if len(self.schemes) <= 1:
            QMessageBox.warning(self, "无法删除", "至少需要保留一个方案。")
            return
        target_name = self.current_scheme_name
        answer = QMessageBox.question(self, "删除方案", f"确定删除方案“{target_name}”吗？")
        if answer != QMessageBox.Yes:
            return
        self.schemes = [item for item in self.schemes if item["name"] != target_name]
        self.current_scheme_name = self.schemes[0]["name"]
        self.save_json(self.scheme_store_path, self.schemes)
        self.refresh_scheme_combo()
        self.apply_scheme_by_name(self.current_scheme_name)
        self.log(f"已删除方案：{target_name}", "#f59e0b")

    def on_select_invoice_dir(self):
        path = QFileDialog.getExistingDirectory(self, "选择发票文件夹")
        if path:
            self.set_invoice_dir(path)

    def on_select_export_dir(self):
        path = QFileDialog.getExistingDirectory(self, "选择导出目录")
        if path:
            self.export_path_edit.setText(path)
            self.save_current_scheme()

    def set_invoice_dir(self, path):
        self.invoice_dir = path
        self.drop_zone.text_label.setText(f"已选择目录：{os.path.basename(path)}")
        self.log(f"加载发票目录：{path}", "#60a5fa")
        self.parse_invoice_directory(auto_export=False)
        self.save_current_scheme()

    def parse_invoice_directory(self, auto_export=False):
        if not self.invoice_dir:
            return

        invoice_map, failed_files = InvoiceParser.parse_directory(self.invoice_dir)
        self.invoice_map = invoice_map
        self.invoice_rows = []
        for order_no, file_path in sorted(invoice_map.items()):
            self.invoice_rows.append(
                {
                    "order_no": order_no,
                    "file_name": os.path.basename(file_path),
                    "file_path": file_path,
                }
            )

        self.refresh_parsed_table()
        self.summary_label.setText(
            f"共解析 {len(self.invoice_rows)} 个订单，异常文件 {len(failed_files)} 个"
        )
        self.refresh_order_table()
        self.log(
            f"解析完成：{len(self.invoice_rows)} 个订单，{len(failed_files)} 个文件未匹配命名规则",
            "#34d399",
        )
        if failed_files:
            self.log(f"未匹配文件：{', '.join(failed_files[:5])}", "#fbbf24")

        if auto_export:
            excel_path = InvoiceParser.generate_excel(invoice_map, self.export_path_edit.text())
            self.latest_excel_path = excel_path
            self.log(f"Excel 已生成：{excel_path}", "#34d399")
            self.show_completion_message("解析完成", f"已完成解析并生成 Excel。\n\n文件位置：{excel_path}")

    def refresh_step_library(self):
        self.step_library.clear()
        for template in STEP_TEMPLATES:
            item = QListWidgetItem(
                f"{template['title']}\n{template['category']} · {template['description']}"
            )
            item.setData(Qt.UserRole, template["type"])
            self.step_library.addItem(item)

    def refresh_element_library(self):
        self.element_library.clear()
        for element in self.elements:
            area = element.get("area", "未写页面位置")
            locator_type = element.get("locator_type", "未设置")
            locator_value = element.get("locator_value", "未填写")
            role = element.get("element_role", "未分类")
            status = element.get("status", "未记录")
            upload_badge = " · 可后台上传" if self.is_upload_compatible_element(element) else ""
            item = QListWidgetItem(
                f"{element['name']} [{role}/{status}{upload_badge}]\n{locator_type}: {locator_value}\n来源：{area}"
            )
            item.setData(Qt.UserRole, element["name"])
            self.element_library.addItem(item)

    def refresh_image_library(self):
        self.image_library.clear()
        for image in self.images:
            item = QListWidgetItem(
                f"{image['name']}\n阈值 {image.get('threshold', 90)}% · {image['file_name']}"
            )
            item.setData(Qt.UserRole, image["name"])
            self.image_library.addItem(item)

    def refresh_parsed_table(self):
        self.parsed_table.setRowCount(len(self.invoice_rows))
        for row_index, row in enumerate(self.invoice_rows):
            self.parsed_table.setItem(row_index, 0, QTableWidgetItem(row["order_no"]))
            self.parsed_table.setItem(row_index, 1, QTableWidgetItem(row["file_name"]))
            self.parsed_table.setItem(row_index, 2, QTableWidgetItem(row["file_path"]))
        self.parsed_table.resizeColumnsToContents()

    def add_step_from_library(self, step_type):
        template = STEP_TEMPLATE_MAP[step_type]
        step = {
            "type": template["type"],
            "title": template["title"],
            "category": template["category"],
            "description": template["description"],
            "config": dict(template["config"]),
        }
        self.workflow_steps.append(step)
        self.refresh_workflow_view(select_index=len(self.workflow_steps) - 1)
        self.log(f"新增流程节点：{template['title']}", "#60a5fa")

    def add_flow_preset(self, preset_name):
        presets = {
            "basic_upload": [
                "open_browser",
                "input_order_no",
                "click_element",
                "click_element",
                "upload_file",
                "press_enter",
                "wait",
                "log",
            ],
            "query_then_upload": [
                "open_browser",
                "input_order_no",
                "click_element",
                "wait_element",
                "click_element",
                "upload_file",
                "press_enter",
                "wait_element",
                "log",
            ],
            "image_fallback": [
                "open_browser",
                "input_order_no",
                "click_element",
                "click_image",
                "upload_file",
                "press_enter",
                "wait_image",
                "log",
            ],
        }
        for step_type in presets.get(preset_name, []):
            template = STEP_TEMPLATE_MAP[step_type]
            self.workflow_steps.append(
                {
                    "type": template["type"],
                    "title": template["title"],
                    "category": template["category"],
                    "description": template["description"],
                    "config": dict(template["config"]),
                }
            )
        self.refresh_workflow_view(select_index=len(self.workflow_steps) - 1)
        self.log("已加入常用流程模板，可在右侧继续细化参数。", "#34d399")

    def step_uses_foreground_io(self, step):
        step_type = step.get("type")
        if step_type == "click_image":
            return True
        if step_type == "upload_file":
            target_name = step.get("config", {}).get("target", "").strip()
            if not target_name:
                return True
            element = self.resolve_element_record(target_name)
            return not self.is_upload_compatible_element(element)
        return False

    def build_step_mode_hint(self, step):
        return "占前台" if self.step_uses_foreground_io(step) else "后台优先"

    def is_upload_step_verified(self, step):
        return bool(step.get("type") == "upload_file" and step.get("config", {}).get("upload_verified"))

    def get_upload_step_status_text(self, step):
        if step.get("type") != "upload_file":
            return ""
        config = step.get("config", {})
        if config.get("upload_verified"):
            target_name = config.get("target") or "自动查找 input[type=file]"
            return f"已验证后台上传 · {target_name}"
        return "未验证后台上传"

    def get_step_config_issue(self, step):
        step_type = step.get("type")
        config = step.get("config", {})
        if step_type == "open_browser" and not (config.get("url") or "").strip():
            return "未设置页面地址"
        if step_type in {
            "click_element",
            "double_click_element",
            "focus_element",
            "wait_element",
            "input_order_no",
            "input_file_name",
            "input_file_path",
            "input_fixed_text",
        } and not (config.get("target") or "").strip():
            return "未绑定目标元素"
        if step_type in {"click_image", "wait_image"} and not (config.get("target") or "").strip():
            return "未绑定目标图片"
        if step_type == "input_fixed_text" and not (config.get("text") or "").strip():
            return "未填写固定内容"
        if step_type == "upload_file" and not (config.get("target") or "").strip():
            return "未绑定上传控件，将依赖自动查找或系统文件框"
        return ""

    def get_step_fix_hint(self, step):
        step_type = step.get("type")
        config = step.get("config", {})
        issue = self.get_step_config_issue(step)
        if not issue:
            return ""
        if step_type == "open_browser":
            return "建议先填写上传页面地址，后续测试节点和正式执行都会复用这里的地址。"
        if step_type in {"click_element", "double_click_element", "focus_element", "wait_element"}:
            return "建议先选中当前节点，再到左侧元素库点击对应元素；如果还没采集元素，可先用“智能获取元素”。"
        if step_type in {"input_order_no", "input_file_name", "input_file_path", "input_fixed_text"} and not (config.get("target") or "").strip():
            return "建议先绑定目标输入框；如果页面里还没有这个元素，先去采集输入框再回来绑定。"
        if step_type == "input_fixed_text" and not (config.get("text") or "").strip():
            return "建议在右侧“输入内容”里填写固定文本，再测试当前节点。"
        if step_type in {"click_image", "wait_image"}:
            return "建议先到左侧图片库导入或选择目标图片，再回到当前节点绑定。"
        if step_type == "upload_file":
            return "建议优先采集网页里的文件上传控件并绑定到当前节点；标准 input[type=file] 可以走后台上传。"
        return "建议先补齐当前节点的必填配置，再继续测试或执行。"

    def get_step_quick_action(self, step):
        step_type = step.get("type")
        config = step.get("config", {})
        issue = self.get_step_config_issue(step)
        if not issue:
            return None, None
        if step_type in {"click_element", "double_click_element", "wait_element"} and not (config.get("target") or "").strip():
            return ("采集目标元素", lambda: self.launch_capture_for_step("目标元素", "按钮", "正在为当前节点打开智能获取元素。"))
        if step_type in {"focus_element", "input_order_no", "input_file_name", "input_file_path", "input_fixed_text"} and not (config.get("target") or "").strip():
            return ("采集输入框", lambda: self.launch_capture_for_step("输入框", "输入框", "正在为当前节点打开智能获取元素（输入框）。"))
        if step_type == "upload_file" and not (config.get("target") or "").strip():
            return ("采集上传控件", lambda: self.launch_capture_for_step("文件上传控件", "上传控件", "正在为当前节点打开智能获取元素（上传控件）。"))
        if step_type in {"click_image", "wait_image"} and not (config.get("target") or "").strip():
            return ("导入图片", self.import_image)
        return None, None

    def is_upload_compatible_element(self, element):
        if not element:
            return False
        if element.get("is_file_input"):
            return True
        tag = (element.get("tag") or "").strip().lower()
        input_type = (element.get("input_type") or "").strip().lower()
        locator_value = (element.get("locator_value") or "").strip().lower()
        css_selector = (element.get("css_selector") or "").strip().lower()
        xpath = (element.get("xpath") or "").strip().lower()
        if tag == "input" and input_type == "file":
            return True
        signals = [locator_value, css_selector, xpath]
        return any("type='file'" in value or 'type="file"' in value or "input[type='file']" in value or 'input[type="file"]' in value for value in signals)

    def suggest_captured_element_name(self, original_name, is_file_input):
        name = (original_name or "").strip()
        if not is_file_input:
            return name
        if not name:
            return "文件上传控件"
        if "上传" in name and "控件" not in name:
            return f"{name}控件"
        if "文件" in name and "控件" not in name:
            return f"{name}控件"
        return name

    def suggest_captured_element_role(self, original_role, is_file_input):
        if is_file_input:
            return "上传控件"
        return original_role

    def refresh_workflow_view(self, select_index=None):
        current_index = self.workflow_list.currentRow() if select_index is None else select_index
        self.workflow_list.clear()
        pending_count = 0
        foreground_count = 0
        for index, step in enumerate(self.workflow_steps, start=1):
            summary = self.build_step_summary(step)
            mode_hint = self.build_step_mode_hint(step)
            config_issue = self.get_step_config_issue(step)
            if config_issue:
                pending_count += 1
            if self.step_uses_foreground_io(step):
                foreground_count += 1
            step_label = f"{step['title']} [{mode_hint}]"
            if config_issue:
                step_label += " [待配置]"
            elif self.is_upload_step_verified(step):
                step_label += " [已验证]"
            item = QListWidgetItem(
                f"{index:02d}  {step_label}\n{step['category']} · {summary}"
            )
            item.setData(Qt.UserRole, step)
            if config_issue:
                item.setBackground(QColor("#fef2f2"))
            elif self.step_uses_foreground_io(step):
                item.setBackground(QColor("#fff7ed"))
            else:
                item.setBackground(QColor("#f8fbff"))
            self.workflow_list.addItem(item)
        total_steps = len(self.workflow_steps)
        configured_count = max(0, total_steps - pending_count)
        self.workflow_status_label.setText(
            f"流程统计：共 {total_steps} 个节点，已配置 {configured_count} 个，待配置 {pending_count} 个，前台节点 {foreground_count} 个"
        )
        self.workflow_status_label.setStyleSheet(
            "color:#991b1b;background:#fef2f2;padding:8px 10px;border-radius:8px;"
            if pending_count
            else "color:#475569;background:#f8fafc;padding:8px 10px;border-radius:8px;"
        )
        if self.workflow_steps:
            target_index = max(0, min(current_index, len(self.workflow_steps) - 1))
            self.workflow_list.setCurrentRow(target_index)
        else:
            self.current_step_index = -1
            self.render_property_panel(None)

    def build_step_summary(self, step):
        config = step.get("config", {})
        step_type = step["type"]
        if step_type in {
            "click_element",
            "double_click_element",
            "focus_element",
            "wait_element",
            "input_order_no",
            "input_file_name",
            "input_file_path",
            "input_fixed_text",
        }:
            return f"元素：{config.get('target') or '未绑定'}"
        if step_type in {"click_image", "wait_image"}:
            return f"图片：{config.get('target') or '未绑定'}，阈值：{config.get('threshold', 90)}%"
        if step_type == "open_browser":
            return f"页面：{config.get('url') or '未设置'}"
        if step_type == "wait":
            return f"等待 {config.get('seconds', 2)} 秒"
        if step_type == "wait_element":
            return f"元素：{config.get('target') or '未绑定'}，超时：{config.get('timeout', 10)} 秒"
        if step_type == "wait_image":
            return f"图片：{config.get('target') or '未绑定'}，超时：{config.get('timeout', 10)} 秒"
        if step_type == "upload_file":
            target = config.get("target") or "自动查找 input[type=file]"
            if not config.get("target"):
                status = self.get_upload_step_status_text(step)
                return f"上传控件：{target} · {status}"
            element = self.resolve_element_record(config.get("target", ""))
            status = "可后台上传" if self.is_upload_compatible_element(element) else "可能回退系统文件框"
            verify_status = self.get_upload_step_status_text(step)
            return f"上传控件：{target} · {status} · {verify_status}"
        if step_type == "input_fixed_text":
            return f"元素：{config.get('target') or '未绑定'}，内容：{config.get('text') or '未填写'}"
        if step_type == "screenshot":
            return f"名称：{config.get('name') or '未命名'}"
        if step_type == "log":
            return config.get("message", "")
        if step_type in {"refresh_page", "press_enter", "press_tab", "delete_current_file"}:
            return "执行后进入下一步"
        return "无额外参数"

    def clear_workflow(self):
        self.workflow_steps.clear()
        self.refresh_workflow_view()
        self.log("已清空流程画布", "#f59e0b")

    def find_first_problem_step_index(self):
        for index, step in enumerate(self.workflow_steps):
            if self.get_step_config_issue(step):
                return index
        return -1

    def inspect_workflow(self):
        if not self.workflow_steps:
            QMessageBox.information(self, "暂无流程", "请先从左侧节点库搭建流程。")
            return
        config_issues, foreground_steps, unverified_upload_steps = self.build_execution_readiness_report()
        first_problem_index = self.find_first_problem_step_index()
        if first_problem_index >= 0:
            self.refresh_workflow_view(select_index=first_problem_index)
            message = "已定位到第一个待配置节点。\n\n" + "\n".join(config_issues[:8])
            if len(config_issues) > 8:
                message += f"\n\n另有 {len(config_issues) - 8} 个节点待配置。"
            QMessageBox.warning(self, "流程体检结果", message)
            self.log(f"流程体检发现 {len(config_issues)} 个待配置节点，已定位到第一个问题节点。", "#ef4444")
            return
        summary = "流程体检通过：当前没有待配置节点。"
        if unverified_upload_steps:
            summary += "\n\n以下上传节点尚未做后台上传验证：\n" + "\n".join(unverified_upload_steps[:8])
            if len(unverified_upload_steps) > 8:
                summary += f"\n另有 {len(unverified_upload_steps) - 8} 个未验证上传节点。"
        if foreground_steps:
            summary += "\n\n以下节点执行时仍会占用前台鼠标/键盘：\n" + "\n".join(foreground_steps[:8])
            if len(foreground_steps) > 8:
                summary += f"\n另有 {len(foreground_steps) - 8} 个前台节点。"
        QMessageBox.information(self, "流程体检结果", summary)
        self.log("流程体检通过：未发现待配置节点。", "#34d399")

    def remove_step(self):
        index = self.workflow_list.currentRow()
        if index < 0:
            return
        removed = self.workflow_steps.pop(index)
        self.refresh_workflow_view(select_index=index - 1)
        self.log(f"已删除节点：{removed['title']}", "#f59e0b")

    def move_step(self, direction):
        index = self.workflow_list.currentRow()
        new_index = index + direction
        if index < 0 or new_index < 0 or new_index >= len(self.workflow_steps):
            return
        self.workflow_steps[index], self.workflow_steps[new_index] = (
            self.workflow_steps[new_index],
            self.workflow_steps[index],
        )
        self.refresh_workflow_view(select_index=new_index)

    def on_step_selected(self, index):
        self.current_step_index = index
        step = self.workflow_steps[index] if 0 <= index < len(self.workflow_steps) else None
        self.render_property_panel(step)

    def render_property_panel(self, step):
        while self.property_layout.count():
            item = self.property_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        if not step:
            empty = QLabel("选择一个流程节点后，在这里配置目标元素、图片和变量绑定。")
            empty.setWordWrap(True)
            empty.setStyleSheet("color:#64748b;")
            self.property_layout.addWidget(empty)
            self.preview_box.clear()
            return

        title = QLabel(step["title"])
        title.setStyleSheet("font-size:18px;font-weight:700;color:#1e293b;")
        desc = QLabel(step["description"])
        desc.setWordWrap(True)
        desc.setStyleSheet("color:#64748b;")
        self.property_layout.addWidget(title)
        self.property_layout.addWidget(desc)

        mode_hint = QLabel(
            "执行方式：该节点会占用前台鼠标/键盘"
            if self.step_uses_foreground_io(step)
            else "执行方式：该节点优先走后台浏览器控制"
        )
        mode_hint.setWordWrap(True)
        mode_hint.setStyleSheet(
            "color:#9a3412;background:#fff7ed;padding:10px;border-radius:10px;"
            if self.step_uses_foreground_io(step)
            else "color:#166534;background:#f0fdf4;padding:10px;border-radius:10px;"
        )
        self.property_layout.addWidget(mode_hint)

        config_issue = self.get_step_config_issue(step)
        if config_issue:
            issue_hint = QLabel(f"配置提醒：{config_issue}")
            issue_hint.setWordWrap(True)
            issue_hint.setStyleSheet("color:#991b1b;background:#fef2f2;padding:10px;border-radius:10px;")
            self.property_layout.addWidget(issue_hint)
            fix_hint = self.get_step_fix_hint(step)
            if fix_hint:
                action_hint = QLabel(f"修复建议：{fix_hint}")
                action_hint.setWordWrap(True)
                action_hint.setStyleSheet("color:#92400e;background:#fffbeb;padding:10px;border-radius:10px;")
                self.property_layout.addWidget(action_hint)
            action_label, action_handler = self.get_step_quick_action(step)
            if action_label and action_handler:
                quick_action_btn = QPushButton(action_label)
                quick_action_btn.clicked.connect(action_handler)
                quick_action_btn.setStyleSheet(
                    "background:#2563eb;color:white;font-weight:700;padding:8px 12px;border-radius:8px;"
                )
                self.property_layout.addWidget(quick_action_btn)

        form = QWidget()
        form_layout = QFormLayout(form)
        form_layout.setContentsMargins(0, 8, 0, 8)
        form_layout.setSpacing(10)

        name_edit = QLineEdit(step["title"])
        name_edit.textChanged.connect(self.update_step_title)
        form_layout.addRow("节点名称", name_edit)

        step_type = step["type"]
        config = step["config"]

        if step_type in {
            "click_element",
            "double_click_element",
            "focus_element",
            "wait_element",
            "input_order_no",
            "input_file_name",
            "input_file_path",
            "input_fixed_text",
        }:
            target_edit = QLineEdit(config.get("target", ""))
            target_edit.setPlaceholderText("先选中当前节点，再点左侧元素库即可自动绑定")
            target_edit.textChanged.connect(lambda value: self.update_step_config("target", value))
            form_layout.addRow("目标元素", target_edit)

        if step_type in {"click_image", "wait_image"}:
            image_edit = QLineEdit(config.get("target", ""))
            image_edit.setPlaceholderText("先选中当前节点，再点左侧图片库即可自动绑定")
            image_edit.textChanged.connect(lambda value: self.update_step_config("target", value))
            threshold_box = QSpinBox()
            threshold_box.setRange(50, 100)
            threshold_box.setValue(int(config.get("threshold", 90)))
            threshold_box.valueChanged.connect(
                lambda value: self.update_step_config("threshold", value)
            )
            form_layout.addRow("目标图片", image_edit)
            form_layout.addRow("相似度阈值", threshold_box)
            if step_type == "wait_image":
                timeout_box = QSpinBox()
                timeout_box.setRange(1, 120)
                timeout_box.setValue(int(config.get("timeout", 10)))
                timeout_box.valueChanged.connect(
                    lambda value: self.update_step_config("timeout", value)
                )
                form_layout.addRow("等待超时", timeout_box)

        if step_type == "open_browser":
            url_edit = QLineEdit(config.get("url", ""))
            url_edit.setPlaceholderText("https://example.com/upload")
            url_edit.textChanged.connect(lambda value: self.update_step_config("url", value))
            form_layout.addRow("上传页面", url_edit)

        if step_type == "wait":
            seconds_box = QSpinBox()
            seconds_box.setRange(1, 999)
            seconds_box.setValue(int(config.get("seconds", 2)))
            seconds_box.valueChanged.connect(
                lambda value: self.update_step_config("seconds", value)
            )
            form_layout.addRow("等待秒数", seconds_box)

        if step_type == "wait_element":
            timeout_box = QSpinBox()
            timeout_box.setRange(1, 120)
            timeout_box.setValue(int(config.get("timeout", 10)))
            timeout_box.valueChanged.connect(
                lambda value: self.update_step_config("timeout", value)
            )
            form_layout.addRow("等待超时", timeout_box)

        if step_type in {"input_order_no", "input_file_name", "input_file_path", "upload_file"}:
            binding = QLineEdit(config.get("binding", ""))
            binding.setReadOnly(True)
            binding.setStyleSheet("background:#f8fafc;color:#475569;")
            form_layout.addRow("变量绑定", binding)

        if step_type == "upload_file":
            target_edit = QLineEdit(config.get("target", ""))
            target_edit.setPlaceholderText("可绑定网页上传控件；留空时自动查找 input[type=file]")
            target_edit.textChanged.connect(lambda value: self.update_step_config("target", value))
            form_layout.addRow("上传控件", target_edit)
            target_name = config.get("target", "").strip()
            target_element = self.resolve_element_record(target_name) if target_name else None
            upload_tip = QLabel(
                "当前绑定元素可直接走网页上传，不需要占用系统文件框。"
                if self.is_upload_compatible_element(target_element)
                else "当前未绑定明确的网页上传控件，执行时可能回退到 Windows 文件框。"
            )
            upload_tip.setWordWrap(True)
            upload_tip.setStyleSheet(
                "color:#166534;background:#f0fdf4;padding:8px;border-radius:8px;"
                if self.is_upload_compatible_element(target_element)
                else "color:#9a3412;background:#fff7ed;padding:8px;border-radius:8px;"
            )
            form_layout.addRow("上传判断", upload_tip)
            verify_label = QLabel(
                "当前上传控件已通过后台上传测试。"
                if self.is_upload_step_verified(step)
                else "当前上传控件尚未做后台上传验证。"
            )
            verify_label.setWordWrap(True)
            verify_label.setStyleSheet(
                "color:#166534;background:#f0fdf4;padding:8px;border-radius:8px;"
                if self.is_upload_step_verified(step)
                else "color:#475569;background:#f8fafc;padding:8px;border-radius:8px;"
            )
            form_layout.addRow("验证状态", verify_label)
            test_upload_btn = QPushButton("测试上传控件")
            test_upload_btn.clicked.connect(self.test_upload_binding_current_step)
            test_upload_btn.setStyleSheet(
                "background:#0f766e;color:white;font-weight:700;padding:8px 12px;border-radius:8px;"
            )
            form_layout.addRow("专项测试", test_upload_btn)

        if step_type == "input_fixed_text":
            text_edit = QLineEdit(config.get("text", ""))
            text_edit.setPlaceholderText("例如：电子发票 / 已核验 / 默认备注")
            text_edit.textChanged.connect(lambda value: self.update_step_config("text", value))
            form_layout.addRow("输入内容", text_edit)

        if step_type == "screenshot":
            name_edit = QLineEdit(config.get("name", ""))
            name_edit.setPlaceholderText("例如：上传成功截图")
            name_edit.textChanged.connect(lambda value: self.update_step_config("name", value))
            form_layout.addRow("截图名称", name_edit)

        if step_type == "log":
            message_edit = QLineEdit(config.get("message", ""))
            message_edit.textChanged.connect(
                lambda value: self.update_step_config("message", value)
            )
            form_layout.addRow("日志内容", message_edit)

        self.property_layout.addWidget(form)

        help_text = QLabel(
            "变量说明：订单号和文件名来自解析结果；元素建议优先保存 CSS 或 XPath，准确率更高。"
        )
        help_text.setWordWrap(True)
        help_text.setStyleSheet("color:#475569;background:#f8fafc;padding:10px;border-radius:10px;")
        self.property_layout.addWidget(help_text)
        self.property_layout.addStretch()
        self.update_preview()

    def update_step_title(self, value):
        if self.current_step_index < 0:
            return
        self.workflow_steps[self.current_step_index]["title"] = value or "未命名节点"
        self.refresh_workflow_view(select_index=self.current_step_index)

    def update_step_config(self, key, value):
        if self.current_step_index < 0:
            return
        step = self.workflow_steps[self.current_step_index]
        step["config"][key] = value
        if step.get("type") == "upload_file" and key == "target":
            step["config"]["upload_verified"] = False
        self.refresh_workflow_view(select_index=self.current_step_index)
        self.update_preview()

    def update_preview(self):
        if self.current_step_index < 0 or self.current_step_index >= len(self.workflow_steps):
            self.preview_box.clear()
            return

        step = self.workflow_steps[self.current_step_index]
        sample = self.invoice_rows[0] if self.invoice_rows else {
            "order_no": "26312000001748879251",
            "file_name": "dzfp_xxx.pdf",
            "file_path": r"C:\invoice\dzfp_xxx.pdf",
        }
        self.preview_box.setPlainText(self.resolve_step_preview(step, sample))

    def resolve_step_preview(self, step, sample_row):
        config = step.get("config", {})
        lines = [f"节点：{step['title']}", f"类型：{step['type']}"]
        if step["type"] == "input_order_no":
            lines.append(f"写入元素：{config.get('target') or '未绑定'}")
            lines.append(f"实际值：{sample_row['order_no']}")
        elif step["type"] == "input_file_name":
            lines.append(f"写入元素：{config.get('target') or '未绑定'}")
            lines.append(f"实际值：{sample_row['file_name']}")
        elif step["type"] == "input_file_path":
            lines.append(f"写入元素：{config.get('target') or '未绑定'}")
            lines.append(f"实际值：{sample_row['file_path']}")
        elif step["type"] == "input_fixed_text":
            lines.append(f"写入元素：{config.get('target') or '未绑定'}")
            lines.append(f"实际值：{config.get('text') or '未填写'}")
        elif step["type"] == "upload_file":
            lines.append(f"优先写入上传控件：{config.get('target') or '自动查找 input[type=file]'}")
            lines.append(f"文件路径：{sample_row['file_path']}")
            if config.get("target"):
                element = self.resolve_element_record(config.get("target", ""))
                lines.append("控件判断：可后台上传" if self.is_upload_compatible_element(element) else "控件判断：可能回退系统文件框")
            lines.append(f"验证状态：{self.get_upload_step_status_text(step)}")
        elif step["type"] in {"click_element", "double_click_element", "focus_element"}:
            lines.append(f"定位元素：{config.get('target') or '未绑定'}")
        elif step["type"] == "wait_element":
            lines.append(f"等待元素：{config.get('target') or '未绑定'}")
            lines.append(f"超时：{config.get('timeout', 10)} 秒")
        elif step["type"] in {"click_image", "wait_image"}:
            lines.append(
                f"定位图片：{config.get('target') or '未绑定'}，阈值 {config.get('threshold', 90)}%"
            )
            if step["type"] == "wait_image":
                lines.append(f"超时：{config.get('timeout', 10)} 秒")
        elif step["type"] == "wait":
            lines.append(f"等待 {config.get('seconds', 2)} 秒")
        elif step["type"] == "open_browser":
            lines.append(f"打开页面：{config.get('url') or '未设置'}")
        elif step["type"] == "refresh_page":
            lines.append("刷新当前页面")
        elif step["type"] == "press_enter":
            lines.append("发送 Enter")
        elif step["type"] == "press_tab":
            lines.append("发送 Tab")
        elif step["type"] == "delete_current_file":
            lines.append(f"删除文件：{sample_row['file_name']}")
        elif step["type"] == "screenshot":
            lines.append(f"保存截图：{config.get('name') or '未命名'}")
        elif step["type"] == "log":
            lines.append(f"输出日志：{config.get('message', '')}")
        else:
            lines.append("无额外参数")
        config_issue = self.get_step_config_issue(step)
        if config_issue:
            lines.append(f"配置提醒：{config_issue}")
        lines.append(f"执行方式：{self.build_step_mode_hint(step)}")
        return "\n".join(lines)

    def add_element(self):
        dialog = ElementEditorDialog(self)
        if dialog.exec() != QDialog.Accepted:
            return
        element = dialog.get_data()
        if not element["name"]:
            QMessageBox.warning(self, "信息不完整", "请至少填写元素名称。")
            return
        self.elements.append(element)
        self.save_json(self.get_scheme_element_store_path(self.current_scheme_name), self.elements)
        self.refresh_element_library()
        self.log(f"元素库新增：{element['name']}", "#34d399")

    def suggest_capture_defaults(self):
        role_options = ["输入框", "按钮", "上传控件", "上传入口", "查询入口", "确认按钮", "页面标签", "弹窗", "其他"]
        default_name = ""
        default_role = "其他"
        if self.current_step_index < 0 or self.current_step_index >= len(self.workflow_steps):
            return default_name, default_role, role_options

        step = self.workflow_steps[self.current_step_index]
        step_type = step.get("type")
        step_title = (step.get("title") or "").strip()
        if step_type in {"input_order_no", "input_file_name", "input_file_path", "input_fixed_text", "focus_element"}:
            default_role = "输入框"
            default_name = step_title or "输入框"
        elif step_type in {"click_element", "double_click_element"}:
            default_role = "按钮"
            default_name = step_title or "按钮"
        elif step_type == "wait_element":
            default_role = "页面标签"
            default_name = step_title or "页面元素"
        elif step_type == "upload_file":
            default_role = "上传控件"
            default_name = "文件上传控件"
        elif step_type == "press_enter":
            default_role = "确认按钮"
            default_name = "确认按钮"

        type_based_names = {
            "input_order_no": "订单号输入框",
            "input_file_name": "文件名输入框",
            "input_file_path": "文件路径输入框",
            "click_element": "按钮",
            "double_click_element": "按钮",
            "wait_element": "页面元素",
            "upload_file": "文件上传控件",
        }
        default_name = type_based_names.get(step_type, default_name) or default_name
        return default_name, default_role, role_options

    def capture_element_with_defaults(self, default_name="", default_role="其他"):
        reuse_existing_browser = bool(self.browser_manager and self.browser_manager.is_available())
        default_page_url = ""
        if reuse_existing_browser:
            default_page_url = (self.browser_manager.current_url() or "").strip()
        if not default_page_url:
            default_page_url = self.capture_default_url
        workflow_url = (self.get_browser_start_url() or "").strip()
        if not default_page_url and workflow_url:
            default_page_url = workflow_url
        if default_page_url == "https://example.com" and workflow_url:
            default_page_url = workflow_url

        resolved_page_url = default_page_url.strip()
        if not reuse_existing_browser and (not resolved_page_url or resolved_page_url == "https://example.com"):
            page_url, ok = QInputDialog.getText(
                self,
                "打开采集页面",
                "页面地址",
                text=default_page_url,
            )
            if not ok or not page_url.strip():
                return
            resolved_page_url = page_url.strip()

        self.capture_default_url = resolved_page_url

        suggested_name, suggested_role, role_options = self.suggest_capture_defaults()
        merged_name = default_name or suggested_name
        merged_role = default_role if default_role in role_options else suggested_role
        name, ok = QInputDialog.getText(self, "元素名称", "给这个元素起个名字", text=merged_name)
        if not ok or not name.strip():
            return

        role, ok = QInputDialog.getItem(
            self,
            "元素用途",
            "选择元素用途",
            role_options,
            role_options.index(merged_role) if merged_role in role_options else 0,
            False,
        )
        if not ok:
            return

        if self.capture_thread and self.capture_thread.is_alive():
            QMessageBox.information(self, "正在采集", "已有一个采集窗口正在运行，请先完成当前采集。")
            return

        self.capture_context = {
            "name": name.strip(),
            "role": role,
            "url": resolved_page_url,
            "scheme_name": self.current_scheme_name,
            "reuse_browser": reuse_existing_browser,
        }
        self.capture_thread = threading.Thread(
            target=self._run_capture_session,
            args=(self.capture_context,),
            daemon=True,
        )
        self.capture_thread.start()

    def capture_element(self):
        self.capture_element_with_defaults()

    def launch_capture_for_step(self, default_name, default_role, log_message):
        self.log(log_message, "#60a5fa")
        self.capture_element_with_defaults(default_name, default_role)

    def open_login_browser(self):
        page_url, ok = QInputDialog.getText(
            self,
            "打开登录页面",
            "页面地址",
            text=self.capture_default_url,
        )
        if not ok or not page_url.strip():
            return
        self.capture_default_url = page_url.strip()
        thread = threading.Thread(
            target=self._run_login_browser_session,
            args=(self.capture_default_url, self.current_scheme_name),
            daemon=True,
        )
        thread.start()
        self.log("已打开方案登录浏览器。登录完成后直接关闭浏览器即可保留状态。", "#60a5fa")

    def _run_login_browser_session(self, page_url, scheme_name):
        manager = BrowserManager()
        try:
            manager.start(page_url, user_data_dir=self.get_scheme_profile_dir(scheme_name))
            while manager.context and len(manager.context.pages) > 0:
                threading.Event().wait(1)
        except Exception as exc:
            self.browser_status_signal.emit(f"打开登录浏览器失败：{exc}")
        finally:
            try:
                manager.stop()
            except Exception:
                pass

    def clear_scheme_login_state(self):
        profile_dir = self.get_scheme_profile_dir(self.current_scheme_name)
        if not os.path.isdir(profile_dir):
            QMessageBox.information(self, "无需清理", "当前方案还没有保存过登录状态。")
            return
        answer = QMessageBox.question(
            self,
            "清除登录状态",
            f"确定清除方案“{self.current_scheme_name}”的浏览器登录状态吗？",
        )
        if answer != QMessageBox.Yes:
            return
        shutil.rmtree(profile_dir, ignore_errors=True)
        self.log(f"已清除方案登录状态：{self.current_scheme_name}", "#f59e0b")

    def get_element_by_name(self, element_name):
        return next((item for item in self.elements if item["name"] == element_name), None)

    def test_selected_element(self):
        item = self.element_library.currentItem()
        if not item:
            QMessageBox.information(self, "未选择元素", "请先在元素库里选中一个元素。")
            return
        element = self.get_element_by_name(item.data(Qt.UserRole))
        if not element:
            return
        page_url, ok = QInputDialog.getText(
            self,
            "测试元素定位",
            "页面地址",
            text=self.capture_default_url,
        )
        if not ok or not page_url.strip():
            return
        self.capture_default_url = page_url.strip()
        thread = threading.Thread(
            target=self._run_locator_test,
            args=(self.capture_default_url, element, self.current_scheme_name),
            daemon=True,
        )
        thread.start()

    def _run_locator_test(self, page_url, element, scheme_name):
        manager = BrowserManager()
        try:
            self.browser_status_signal.emit(f"开始测试元素定位：{element['name']}")
            manager.test_locator(
                page_url,
                element.get("locator_type", "CSS 选择器"),
                element.get("locator_value", ""),
                user_data_dir=self.get_scheme_profile_dir(scheme_name),
            )
            self.browser_status_signal.emit(f"元素定位成功：{element['name']}")
        except Exception as exc:
            self.browser_status_signal.emit(f"元素定位失败：{exc}")
        finally:
            try:
                manager.stop()
            except Exception:
                pass

    def _run_capture_session(self, capture_context):
        manager = self.browser_manager if self.browser_manager and self.browser_manager.is_available() else None
        started_new_browser = False
        if not manager:
            manager = BrowserManager()
            self.browser_manager = manager
            started_new_browser = True
        try:
            if started_new_browser:
                self.browser_status_signal.emit("正在打开采集浏览器，请稍等...")
                manager.start(
                    capture_context["url"],
                    user_data_dir=self.get_scheme_profile_dir(capture_context["scheme_name"]),
                )
            else:
                self.browser_status_signal.emit("已复用当前采集浏览器，无需重新打开页面。")
            manager.enable_picker()
            self.browser_status_signal.emit("浏览器已进入采集模式：普通点击采集元素，按住 Shift 再点击可正常打开链接或切换页面；采完后浏览器会保持打开，方便继续采下一个元素。")
            result = manager.wait_for_pick(timeout=300)
            if not result:
                self.browser_status_signal.emit("元素采集超时或未成功。")
                return
            payload = dict(capture_context)
            payload["url"] = manager.current_url() or capture_context["url"]
            payload.update(result)
            self.element_picked_signal.emit(payload)
        except Exception as exc:
            self.browser_status_signal.emit(f"元素采集失败：{exc}")
        finally:
            self.capture_thread = None
            if not manager.is_available():
                try:
                    manager.stop()
                except Exception:
                    pass
                self.browser_manager = None

    def handle_browser_status(self, message):
        self.log(message, "#60a5fa")

    def handle_picked_element(self, payload):
        css_selector = payload.get("css", "").strip()
        xpath = payload.get("xpath", "").strip()
        text_hint = payload.get("text", "").strip()
        tag = payload.get("tag", "").strip().lower()
        input_type = payload.get("inputType", "").strip().lower()
        is_file_input = bool(payload.get("isFileInput"))
        suggested_name = self.suggest_captured_element_name(payload.get("name", ""), is_file_input)
        suggested_role = self.suggest_captured_element_role(payload.get("role", ""), is_file_input)

        if not css_selector and not xpath:
            self.log("采集到了元素，但没有生成可用定位表达式。", "#ef4444")
            return

        locator_type = "CSS 选择器"
        locator_value = css_selector
        if css_selector and xpath:
            locator_type, ok = QInputDialog.getItem(
                self,
                "选择主定位方式",
                "该元素同时生成了 CSS 和 XPath，请选择主定位方式",
                ["CSS 选择器", "XPath"],
                0,
                False,
            )
            if not ok:
                return
            locator_value = css_selector if locator_type == "CSS 选择器" else xpath
        elif xpath:
            locator_type = "XPath"
            locator_value = xpath

        element = {
            "name": suggested_name,
            "element_role": suggested_role,
            "locator_type": locator_type,
            "locator_value": locator_value,
            "area": payload["url"],
            "note": f"标签: {payload.get('tag', '')}；类型: {payload.get('inputType', '') or '无'}；文本: {text_hint}" if text_hint else f"标签: {payload.get('tag', '')}；类型: {payload.get('inputType', '') or '无'}",
            "status": "已采集",
            "css_selector": css_selector,
            "xpath": xpath,
            "tag": tag,
            "input_type": input_type,
            "is_file_input": is_file_input,
            "accept": payload.get("accept", "").strip(),
        }

        self.elements = [item for item in self.elements if item["name"] != element["name"]]
        self.elements.append(element)
        self.save_json(self.get_scheme_element_store_path(self.current_scheme_name), self.elements)
        self.refresh_element_library()
        auto_bound_step = None
        if self.current_step_index >= 0 and self.workflow_steps[self.current_step_index]["type"] in {
            "click_element",
            "double_click_element",
            "focus_element",
            "wait_element",
            "input_order_no",
            "input_file_name",
            "input_file_path",
            "input_fixed_text",
            "upload_file",
        }:
            self.workflow_steps[self.current_step_index]["config"]["target"] = element["name"]
            auto_bound_step = self.workflow_steps[self.current_step_index]["title"]
            self.refresh_workflow_view(select_index=self.current_step_index)
        self.log(
            f"已采集元素：{element['name']}，优先保存为 {locator_type}，CSS 和 XPath 都已记录。",
            "#34d399",
        )
        if auto_bound_step:
            self.log(f"元素“{element['name']}”已自动绑定到当前节点：{auto_bound_step}。", "#60a5fa")
        if is_file_input:
            if payload.get("name", "").strip() != suggested_name:
                self.log(f"已将上传控件名称优化为“{suggested_name}”，便于后续绑定。", "#22c55e")
            self.log(f"元素“{element['name']}”识别为网页上传控件，可直接绑定到“上传文件”节点。", "#22c55e")
            if auto_bound_step and self.workflow_steps[self.current_step_index]["type"] == "upload_file":
                self.log(f"当前上传文件节点已完成绑定，后续可直接测试后台上传。", "#22c55e")
        completion_lines = [f"元素“{element['name']}”已保存到元素库。", "", f"当前主定位：{locator_type}"]
        if auto_bound_step:
            completion_lines.extend(["", f"已自动绑定到节点：{auto_bound_step}"])
        self.show_completion_message(
            "元素采集完成",
            "\n".join(completion_lines),
        )

    def add_common_elements(self):
        common_elements = [
            {"name": "订单号输入框", "element_role": "输入框", "locator_type": "CSS 选择器", "locator_value": "input[placeholder*='订单']", "area": "页面上方查询区", "note": "每次先填订单号", "status": "已录入"},
            {"name": "查询按钮", "element_role": "查询入口", "locator_type": "XPath", "locator_value": "//button[contains(., '查询')]", "area": "订单号输入框右侧", "note": "填完订单号点击查询", "status": "已录入"},
            {"name": "上传发票按钮", "element_role": "上传入口", "locator_type": "XPath", "locator_value": "//button[contains(., '上传')]", "area": "订单详情区域", "note": "打开文件选择框", "status": "已录入"},
            {"name": "上传确认按钮", "element_role": "确认按钮", "locator_type": "XPath", "locator_value": "//button[contains(., '确认')]", "area": "上传弹窗右下角", "note": "选择文件后确认上传", "status": "已录入"},
        ]
        existing_names = {element["name"] for element in self.elements}
        added = 0
        for element in common_elements:
            if element["name"] not in existing_names:
                self.elements.append(element)
                added += 1
        self.save_json(self.get_scheme_element_store_path(self.current_scheme_name), self.elements)
        self.refresh_element_library()
        self.log(f"已生成 {added} 个常用元素。", "#34d399")

    def remove_selected_element(self):
        item = self.element_library.currentItem()
        if not item:
            return
        name = item.data(Qt.UserRole)
        self.elements = [element for element in self.elements if element["name"] != name]
        self.save_json(self.get_scheme_element_store_path(self.current_scheme_name), self.elements)
        self.refresh_element_library()
        self.log(f"元素库删除：{name}", "#f59e0b")

    def import_image(self):
        source_path, _ = QFileDialog.getOpenFileName(
            self,
            "导入图片",
            "",
            "Images (*.png *.jpg *.jpeg *.bmp)",
        )
        if not source_path:
            return

        name, ok = QInputDialog.getText(
            self,
            "图片名称",
            "图片名称",
            text=os.path.splitext(os.path.basename(source_path))[0],
        )
        if not ok or not name.strip():
            return

        file_name = os.path.basename(source_path)
        target_path = os.path.join(self.get_scheme_image_asset_dir(self.current_scheme_name), file_name)
        if os.path.abspath(source_path) != os.path.abspath(target_path):
            shutil.copy2(source_path, target_path)

        self.images.append(
            {
                "name": name.strip(),
                "file_name": file_name,
                "path": target_path,
                "threshold": 90,
            }
        )
        self.save_json(self.get_scheme_image_store_path(self.current_scheme_name), self.images)
        self.refresh_image_library()
        self.log(f"图片库导入：{name.strip()} -> {target_path}", "#34d399")

    def bind_selected_element(self, element_name):
        if self.current_step_index < 0:
            QMessageBox.information(self, "未选择节点", "请先在中间流程画布里选中一个节点，再点击左侧元素条目进行绑定。")
            self.log("元素绑定未生效：当前还没有选中流程节点。", "#f59e0b")
            return
        step = self.workflow_steps[self.current_step_index]
        if step["type"] not in {
            "click_element",
            "double_click_element",
            "focus_element",
            "wait_element",
            "input_order_no",
            "input_file_name",
            "input_file_path",
            "input_fixed_text",
            "upload_file",
        }:
            QMessageBox.information(self, "节点类型不匹配", f"当前节点“{step['title']}”不支持绑定元素，请先选择元素类节点。")
            self.log(f"元素绑定未生效：当前节点“{step['title']}”不是可绑定元素的类型。", "#f59e0b")
            return
        step["config"]["target"] = element_name
        if step["type"] == "upload_file":
            step["config"]["upload_verified"] = False
        self.refresh_workflow_view(select_index=self.current_step_index)
        self.log(f"节点已绑定元素：{element_name}", "#60a5fa")

    def bind_selected_image(self, image_name):
        if self.current_step_index < 0:
            QMessageBox.information(self, "未选择节点", "请先在中间流程画布里选中一个节点，再点击左侧图片条目进行绑定。")
            self.log("图片绑定未生效：当前还没有选中流程节点。", "#f59e0b")
            return
        step = self.workflow_steps[self.current_step_index]
        if step["type"] not in {"click_image", "wait_image"}:
            QMessageBox.information(self, "节点类型不匹配", f"当前节点“{step['title']}”不支持绑定图片，请先选择图片类节点。")
            self.log(f"图片绑定未生效：当前节点“{step['title']}”不是可绑定图片的类型。", "#f59e0b")
            return
        step["config"]["target"] = image_name
        self.refresh_workflow_view(select_index=self.current_step_index)
        self.log(f"节点已绑定图片：{image_name}", "#60a5fa")

    def remove_selected_image(self):
        item = self.image_library.currentItem()
        if not item:
            return
        name = item.data(Qt.UserRole)
        target = next((image for image in self.images if image["name"] == name), None)
        self.images = [image for image in self.images if image["name"] != name]
        self.save_json(self.get_scheme_image_store_path(self.current_scheme_name), self.images)
        self.refresh_image_library()
        if target and os.path.exists(target["path"]):
            try:
                os.remove(target["path"])
            except OSError:
                pass
        self.log(f"图片库删除：{name}", "#f59e0b")

    def get_browser_start_url(self):
        for step in self.workflow_steps:
            if step.get("type") == "open_browser":
                return step.get("config", {}).get("url") or self.capture_default_url
        return self.capture_default_url

    def resolve_element_record(self, element_name):
        return next((item for item in self.elements if item["name"] == element_name), None)

    def resolve_image_record(self, image_name):
        return next((item for item in self.images if item["name"] == image_name), None)

    def execute_workflow_for_order(self, manager, row):
        for step in self.workflow_steps:
            step_type = step["type"]
            config = step.get("config", {})
            if step_type == "open_browser":
                continue
            if step_type == "refresh_page":
                manager.refresh()
            elif step_type == "click_element":
                element = self.resolve_element_record(config.get("target", ""))
                if element:
                    manager.click(element["locator_type"], element["locator_value"])
            elif step_type == "double_click_element":
                element = self.resolve_element_record(config.get("target", ""))
                if element:
                    manager.click(element["locator_type"], element["locator_value"], click_count=2)
            elif step_type == "focus_element":
                element = self.resolve_element_record(config.get("target", ""))
                if element:
                    manager.focus(element["locator_type"], element["locator_value"])
            elif step_type == "wait_element":
                element = self.resolve_element_record(config.get("target", ""))
                if element:
                    manager.wait_for(
                        element["locator_type"],
                        element["locator_value"],
                        timeout=int(config.get("timeout", 10)) * 1000,
                    )
            elif step_type in {"input_order_no", "input_file_name", "input_file_path", "input_fixed_text"}:
                element = self.resolve_element_record(config.get("target", ""))
                if not element:
                    continue
                if step_type == "input_order_no":
                    value = row["order_no"]
                elif step_type == "input_file_name":
                    value = row["file_name"]
                elif step_type == "input_file_path":
                    value = row["file_path"]
                else:
                    value = config.get("text", "")
                manager.fill(element["locator_type"], element["locator_value"], value)
            elif step_type == "wait":
                threading.Event().wait(int(config.get("seconds", 2)))
            elif step_type == "log":
                self.log(config.get("message", "进入下一步"), "#94a3b8")
            elif step_type in {"click_image", "wait_image", "upload_file", "press_enter", "press_tab", "delete_current_file", "screenshot"}:
                self.log(f"当前节点暂未接入自动执行，已跳过：{step['title']}", "#fbbf24")

    def build_execution_readiness_report(self):
        config_issues = []
        foreground_steps = []
        unverified_upload_steps = []
        for index, step in enumerate(self.workflow_steps, start=1):
            issue = self.get_step_config_issue(step)
            if issue:
                config_issues.append(f"{index:02d}. {step['title']}：{issue}")
            if self.step_uses_foreground_io(step):
                foreground_steps.append(f"{index:02d}. {step['title']}")
            if step.get("type") == "upload_file" and step.get("config", {}).get("target") and not issue:
                element = self.resolve_element_record(step.get("config", {}).get("target", ""))
                if self.is_upload_compatible_element(element) and not self.is_upload_step_verified(step):
                    unverified_upload_steps.append(f"{index:02d}. {step['title']}")
        return config_issues, foreground_steps, unverified_upload_steps

    def build_single_step_readiness(self, step, index):
        issue = self.get_step_config_issue(step)
        config_issues = [f"{index + 1:02d}. {step['title']}：{issue}"] if issue else []
        foreground_steps = [f"{index + 1:02d}. {step['title']}"] if self.step_uses_foreground_io(step) else []
        return config_issues, foreground_steps

    def run_actual_automation(self):
        manager = BrowserManager()
        try:
            if not self.latest_excel_path:
                self.latest_excel_path = InvoiceParser.generate_excel(self.invoice_map, self.export_path_edit.text())
                self.log(f"执行前已自动生成结果Excel：{self.latest_excel_path}", "#34d399")
            _, foreground_steps, unverified_upload_steps = self.build_execution_readiness_report()
            if foreground_steps:
                self.log(f"以下节点执行时请勿操作鼠标键盘：{', '.join(foreground_steps)}", "#f59e0b")
            else:
                self.log("当前流程节点均为后台优先执行。", "#34d399")
            if unverified_upload_steps:
                self.log(f"以下上传节点尚未验证后台上传能力：{', '.join(unverified_upload_steps)}", "#f59e0b")
            start_url = self.get_browser_start_url()
            manager.start(
                start_url,
                user_data_dir=self.get_scheme_profile_dir(self.current_scheme_name),
            )
            total = len(self.invoice_rows)
            success = 0
            failed = 0
            self.update_run_stats(total=total, success=0, failed=0)
            for row in self.invoice_rows:
                order_success = False
                last_error = ""
                for attempt in range(1, self.retry_spin.value() + 1):
                    try:
                        self.log(f"开始执行订单：{row['order_no']}，第 {attempt} 次", "#e2e8f0")
                        self.execute_workflow_for_order_runtime(manager, row)
                        InvoiceParser.update_excel_status(
                            self.latest_excel_path,
                            row["order_no"],
                            "成功",
                            f"执行完成，第 {attempt} 次成功",
                        )
                        success += 1
                        order_success = True
                        break
                    except Exception as exc:
                        last_error = str(exc)
                        self.log(f"订单执行失败：{row['order_no']}，第 {attempt} 次，原因：{exc}", "#ef4444")
                if order_success:
                    self.update_order_table_row(row["order_no"], "成功", f"第 {attempt} 次执行成功")
                else:
                    failed += 1
                    InvoiceParser.update_excel_status(
                        self.latest_excel_path,
                        row["order_no"],
                        "失败",
                        last_error,
                    )
                    self.update_order_table_row(row["order_no"], "失败", last_error)
                self.update_run_stats(total=total, success=success, failed=failed)
            self.show_completion_message(
                "执行完成",
                f"实际执行已结束。\n\n成功处理：{success} / {total}\n失败：{failed}\n结果Excel：{self.latest_excel_path}",
            )
        finally:
            try:
                manager.stop()
            except Exception:
                pass

    def execute_workflow_for_order_runtime(self, manager, row, steps=None):
        for step in (steps or self.workflow_steps):
            step_type = step["type"]
            config = step.get("config", {})
            if step_type == "open_browser":
                continue
            if step_type == "refresh_page":
                manager.refresh()
            elif step_type == "click_element":
                element = self.resolve_element_record(config.get("target", ""))
                if element:
                    manager.click(element["locator_type"], element["locator_value"])
            elif step_type == "double_click_element":
                element = self.resolve_element_record(config.get("target", ""))
                if element:
                    manager.click(element["locator_type"], element["locator_value"], click_count=2)
            elif step_type == "focus_element":
                element = self.resolve_element_record(config.get("target", ""))
                if element:
                    manager.focus(element["locator_type"], element["locator_value"])
            elif step_type == "wait_element":
                element = self.resolve_element_record(config.get("target", ""))
                if element:
                    manager.wait_for(
                        element["locator_type"],
                        element["locator_value"],
                        timeout=int(config.get("timeout", 10)) * 1000,
                    )
            elif step_type in {"input_order_no", "input_file_name", "input_file_path", "input_fixed_text"}:
                element = self.resolve_element_record(config.get("target", ""))
                if not element:
                    continue
                if step_type == "input_order_no":
                    value = row["order_no"]
                elif step_type == "input_file_name":
                    value = row["file_name"]
                elif step_type == "input_file_path":
                    value = row["file_path"]
                else:
                    value = config.get("text", "")
                manager.fill(element["locator_type"], element["locator_value"], value)
            elif step_type == "click_image":
                image = self.resolve_image_record(config.get("target", ""))
                if image:
                    self.log(f"节点“{step['title']}”正在使用图片识别点击，会占用前台鼠标。", "#f59e0b")
                    ok = ImageEngine.click_image(image["path"], threshold=float(config.get("threshold", 90)) / 100)
                    if not ok:
                        raise RuntimeError(f"未找到图片：{image['name']}")
            elif step_type == "wait_image":
                image = self.resolve_image_record(config.get("target", ""))
                if image:
                    pos = ImageEngine.wait_for_image(
                        image["path"],
                        timeout=int(config.get("timeout", 10)),
                        threshold=float(config.get("threshold", 90)) / 100,
                    )
                    if not pos:
                        raise RuntimeError(f"等待图片超时：{image['name']}")
            elif step_type == "upload_file":
                element = self.resolve_element_record(config.get("target", ""))
                uploaded = manager.upload_file(
                    row["file_path"],
                    element.get("locator_type") if element else None,
                    element.get("locator_value") if element else None,
                )
                if not uploaded:
                    if element and not self.is_upload_compatible_element(element):
                        self.log(f"节点“{step['title']}”绑定的元素“{element['name']}”不是标准文件上传控件。", "#f59e0b")
                    self.log(f"节点“{step['title']}”未找到网页上传控件，回退到 Windows 文件框输入。", "#f59e0b")
                    pyautogui.write(row["file_path"])
                    pyautogui.press("enter")
            elif step_type == "press_enter":
                manager.press_key("Enter")
            elif step_type == "press_tab":
                manager.press_key("Tab")
            elif step_type == "wait":
                threading.Event().wait(int(config.get("seconds", 2)))
            elif step_type == "screenshot":
                screenshot_dir = os.path.join(self.get_scheme_data_dir(self.current_scheme_name), "screenshots")
                os.makedirs(screenshot_dir, exist_ok=True)
                name = config.get("name") or f"{row['order_no']}_screenshot"
                filename = f"{name}_{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}.png"
                manager.screenshot(os.path.join(screenshot_dir, filename))
            elif step_type == "delete_current_file":
                if os.path.exists(row["file_path"]):
                    os.remove(row["file_path"])
            elif step_type == "log":
                self.log(config.get("message", "进入下一步"), "#94a3b8")

    def test_current_step(self):
        if self.current_step_index < 0 or not self.invoice_rows:
            QMessageBox.information(self, "无法测试", "请先选择一个流程节点，并确保已解析至少一条发票记录。")
            return
        step = self.workflow_steps[self.current_step_index]
        config_issues, foreground_steps = self.build_single_step_readiness(step, self.current_step_index)
        if config_issues:
            QMessageBox.warning(self, "节点待配置", "当前节点还没有配置完整：\n\n" + "\n".join(config_issues))
            self.log(f"节点测试未开始：{config_issues[0]}", "#ef4444")
            return
        if foreground_steps:
            message = "当前节点测试时会占用前台鼠标/键盘：\n\n" + "\n".join(foreground_steps) + "\n\n确认继续测试吗？"
            answer = QMessageBox.question(self, "测试前确认", message)
            if answer != QMessageBox.Yes:
                self.log("已取消节点测试：用户在测试前确认中终止。", "#f59e0b")
                return
        manager = BrowserManager()
        try:
            manager.start(
                self.get_browser_start_url(),
                user_data_dir=self.get_scheme_profile_dir(self.current_scheme_name),
            )
            self.execute_workflow_for_order_runtime(manager, self.invoice_rows[0], steps=[step])
            self.show_completion_message("节点测试完成", f"节点“{step['title']}”已执行完成。")
        except Exception as exc:
            QMessageBox.warning(self, "节点测试失败", str(exc))
        finally:
            try:
                manager.stop()
            except Exception:
                pass

    def test_upload_binding_current_step(self):
        if self.current_step_index < 0 or not self.invoice_rows:
            QMessageBox.information(self, "无法测试", "请先选择上传文件节点，并确保已解析至少一条发票记录。")
            return
        step = self.workflow_steps[self.current_step_index]
        if step.get("type") != "upload_file":
            QMessageBox.information(self, "节点不匹配", "当前节点不是“上传文件”节点。")
            return
        sample_row = self.invoice_rows[0]
        sample_path = sample_row.get("file_path", "")
        if not sample_path or not os.path.exists(sample_path):
            QMessageBox.warning(self, "文件不存在", "测试上传控件需要一条有效的发票文件路径。")
            return
        config_issues, foreground_steps = self.build_single_step_readiness(step, self.current_step_index)
        if config_issues:
            QMessageBox.warning(self, "节点待配置", "当前上传节点还没有配置完整：\n\n" + "\n".join(config_issues))
            return
        element = self.resolve_element_record(step.get("config", {}).get("target", ""))
        if not self.is_upload_compatible_element(element):
            QMessageBox.warning(self, "控件类型不匹配", "当前绑定元素不是标准上传控件，建议先采集网页里的 input[type=file]。")
            self.log("上传控件专项测试未开始：当前绑定元素不是标准上传控件。", "#ef4444")
            return
        manager = BrowserManager()
        try:
            manager.start(
                self.get_browser_start_url(),
                user_data_dir=self.get_scheme_profile_dir(self.current_scheme_name),
            )
            uploaded, error_message = self.run_upload_binding_check(manager, step, sample_path)
            if not uploaded:
                raise RuntimeError(error_message or "页面未接受该上传控件，后台上传测试失败。")
            step["config"]["upload_verified"] = True
            self.refresh_workflow_view(select_index=self.current_step_index)
            self.update_preview()
            self.show_completion_message(
                "上传控件测试完成",
                f"已成功向控件“{element['name']}”写入测试文件。\n\n测试文件：{sample_path}",
            )
            self.log(f"上传控件专项测试成功：{element['name']}", "#34d399")
        except Exception as exc:
            step["config"]["upload_verified"] = False
            self.refresh_workflow_view(select_index=self.current_step_index)
            self.update_preview()
            QMessageBox.warning(self, "上传控件测试失败", str(exc))
        finally:
            try:
                manager.stop()
            except Exception:
                pass

    def run_upload_binding_check(self, manager, step, sample_path):
        element = self.resolve_element_record(step.get("config", {}).get("target", ""))
        if not element:
            return False, "当前上传节点未绑定上传控件。"
        if not self.is_upload_compatible_element(element):
            return False, "当前绑定元素不是标准上传控件。"
        try:
            uploaded = manager.upload_file(
                sample_path,
                element.get("locator_type"),
                element.get("locator_value"),
            )
        except Exception as exc:
            return False, str(exc)
        if not uploaded:
            return False, "页面未接受该上传控件，后台上传测试失败。"
        return True, ""

    def verify_all_upload_steps(self):
        if not self.workflow_steps:
            QMessageBox.information(self, "暂无流程", "请先从左侧节点库搭建流程。")
            return
        if not self.invoice_rows:
            QMessageBox.warning(self, "缺少数据", "批量验证上传节点前，请先选择并解析发票文件夹。")
            return
        sample_path = self.invoice_rows[0].get("file_path", "")
        if not sample_path or not os.path.exists(sample_path):
            QMessageBox.warning(self, "文件不存在", "批量验证上传节点需要一条有效的发票文件路径。")
            return

        upload_indices = [index for index, step in enumerate(self.workflow_steps) if step.get("type") == "upload_file"]
        if not upload_indices:
            QMessageBox.information(self, "无需验证", "当前流程里没有上传文件节点。")
            return

        manager = BrowserManager()
        passed = []
        failed = []
        first_failed_index = -1
        try:
            manager.start(
                self.get_browser_start_url(),
                user_data_dir=self.get_scheme_profile_dir(self.current_scheme_name),
            )
            for index in upload_indices:
                step = self.workflow_steps[index]
                issue = self.get_step_config_issue(step)
                if issue:
                    step["config"]["upload_verified"] = False
                    failed.append(f"{index + 1:02d}. {step['title']}：{issue}")
                    if first_failed_index < 0:
                        first_failed_index = index
                    continue
                uploaded, error_message = self.run_upload_binding_check(manager, step, sample_path)
                step["config"]["upload_verified"] = bool(uploaded)
                if uploaded:
                    passed.append(f"{index + 1:02d}. {step['title']}")
                else:
                    failed.append(f"{index + 1:02d}. {step['title']}：{error_message}")
                    if first_failed_index < 0:
                        first_failed_index = index
        except Exception as exc:
            QMessageBox.warning(self, "批量验证失败", str(exc))
            return
        finally:
            self.refresh_workflow_view(select_index=self.current_step_index)
            self.update_preview()
            try:
                manager.stop()
            except Exception:
                pass

        lines = [f"已验证上传节点：{len(passed)} 个"]
        if passed:
            lines.append("")
            lines.append("验证通过：")
            lines.extend(passed[:8])
            if len(passed) > 8:
                lines.append(f"另有 {len(passed) - 8} 个通过节点。")
        if failed:
            if first_failed_index >= 0:
                self.refresh_workflow_view(select_index=first_failed_index)
            lines.append("")
            lines.append("验证失败：")
            lines.extend(failed[:8])
            if len(failed) > 8:
                lines.append(f"另有 {len(failed) - 8} 个失败节点。")
            QMessageBox.warning(self, "批量验证上传结果", "\n".join(lines))
            self.log(f"批量验证上传完成：通过 {len(passed)} 个，失败 {len(failed)} 个。", "#f59e0b")
            return

        QMessageBox.information(self, "批量验证上传结果", "\n".join(lines))
        self.log(f"批量验证上传完成：{len(passed)} 个上传节点全部通过。", "#34d399")

    def run_parsing_only(self):
        if not self.invoice_dir:
            QMessageBox.warning(self, "缺少目录", "请先选择发票文件夹。")
            return
        self.parse_invoice_directory(auto_export=True)

    def start_automation(self):
        if not self.invoice_rows:
            QMessageBox.warning(self, "缺少数据", "请先选择并解析发票文件夹。")
            return
        if not self.workflow_steps:
            QMessageBox.warning(self, "缺少流程", "请先从左侧节点库搭建流程。")
            return
        config_issues, foreground_steps, unverified_upload_steps = self.build_execution_readiness_report()
        if config_issues:
            message = "以下节点还没有配置完整，请先处理后再执行：\n\n" + "\n".join(config_issues[:10])
            if len(config_issues) > 10:
                message += f"\n\n另有 {len(config_issues) - 10} 个节点也待配置。"
            QMessageBox.warning(self, "流程待配置", message)
            self.log("执行前校验未通过：存在待配置节点。", "#ef4444")
            return
        if unverified_upload_steps:
            message = "以下上传节点尚未验证后台上传能力：\n\n" + "\n".join(unverified_upload_steps[:10])
            if len(unverified_upload_steps) > 10:
                message += f"\n\n另有 {len(unverified_upload_steps) - 10} 个未验证上传节点。"
            message += "\n\n建议先逐个点击“测试上传控件”。确认继续执行吗？"
            answer = QMessageBox.question(self, "上传节点未验证", message)
            if answer != QMessageBox.Yes:
                self.log("已取消执行：存在未验证的上传节点。", "#f59e0b")
                return
        if foreground_steps:
            message = "以下节点执行时会占用前台鼠标/键盘：\n\n" + "\n".join(foreground_steps[:10])
            if len(foreground_steps) > 10:
                message += f"\n\n另有 {len(foreground_steps) - 10} 个前台节点。"
            message += "\n\n确认继续执行吗？"
            answer = QMessageBox.question(self, "执行前确认", message)
            if answer != QMessageBox.Yes:
                self.log("已取消执行：用户在执行前确认中终止。", "#f59e0b")
                return
        self.log("开始执行真实流程，复用当前方案登录状态。", "#60a5fa")
        self.run_actual_automation()

    def import_image_library(self):
        folder_path = QFileDialog.getExistingDirectory(self, "导入图片库目录")
        if not folder_path:
            return
        manifest_path = os.path.join(folder_path, "images.json")
        imported = self.load_json(manifest_path, [])
        if not isinstance(imported, list):
            QMessageBox.warning(self, "导入失败", "图片库目录中缺少有效的 images.json。")
            return
        target_image_dir = self.get_scheme_image_asset_dir(self.current_scheme_name)
        source_image_dir = os.path.join(folder_path, "images")
        normalized = []
        for image in imported:
            copied = dict(image)
            file_name = copied.get("file_name") or os.path.basename(copied.get("path", ""))
            source_path = os.path.join(source_image_dir, file_name)
            target_path = os.path.join(target_image_dir, file_name)
            if os.path.exists(source_path):
                shutil.copy2(source_path, target_path)
            copied["file_name"] = file_name
            copied["path"] = target_path
            normalized.append(copied)
        self.images = normalized
        self.save_json(self.get_scheme_image_store_path(self.current_scheme_name), self.images)
        self.refresh_image_library()
        self.log(f"已导入图片库目录：{folder_path}", "#34d399")

    def export_image_library(self):
        folder_path = QFileDialog.getExistingDirectory(self, "选择图片库导出目录")
        if not folder_path:
            return
        export_root = os.path.join(folder_path, f"{self.current_scheme_name}_images_export")
        export_image_dir = os.path.join(export_root, "images")
        os.makedirs(export_image_dir, exist_ok=True)
        exported = []
        for image in self.images:
            copied = dict(image)
            if os.path.exists(image.get("path", "")):
                shutil.copy2(image["path"], os.path.join(export_image_dir, image["file_name"]))
            copied["path"] = os.path.join("images", image["file_name"])
            exported.append(copied)
        self.save_json(os.path.join(export_root, "images.json"), exported)
        self.log(f"已导出图片库目录：{export_root}", "#34d399")

    def closeEvent(self, event):
        self.save_current_scheme()
        super().closeEvent(event)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = RPAMainWindow()
    window.show()
    sys.exit(app.exec())
