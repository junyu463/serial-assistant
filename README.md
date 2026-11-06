# 串口助手（Serial Assistant）

基于 **PySide6 + pyserial** 的串口调试工具，界面参考 Windows 11 Fluent Design，适配 Windows 10/11 与高 DPI 缩放。

## 功能

- 串口参数全部可配置：串口号（自动扫描 / 手动输入）、波特率（常用值 + 自定义）、数据位、停止位、校验位、流控
- 打开 / 关闭串口，按钮与状态标签同步切换配色
- 接收区、发送区均支持「文本 / HEX」模式，文本按 GBK 编解码
- 接收「覆盖」模式：勾选后新数据覆盖上一次显示，未勾选则追加
- 暂停接收：只暂停界面刷新，后台仍继续读取并统计字节数
- 定时发送：可配置毫秒间隔，串口断开或发送失败自动停止
- 发送新行：自动追加 `\n`
- 状态栏实时显示接收 / 发送字节数
- 一键清空接收区 / 发送区，接收数据可导出为 TXT

## 获取源码

```powershell
git clone https://github.com/junyu463/serial-assistant.git
cd serial-assistant
```

## 环境要求

- Windows 10 / 11
- Python 3.9+（已在 Python 3.13 上验证）
- PySide6、pyserial

## 安装依赖

```powershell
python -m pip install -r requirements.txt
```

或手动安装：

```powershell
python -m pip install PySide6 pyserial
```

国内网络可使用镜像加速：

```powershell
python -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt
```

## 运行

```powershell
python main.py
```

## 打包为 Windows 可执行文件

```powershell
python -m pip install pyinstaller

pyinstaller --noconfirm --windowed --name SerialAssistant `
  --exclude-module PySide6.QtWebEngineCore `
  --exclude-module PySide6.QtWebEngineWidgets `
  --exclude-module PySide6.QtPdf `
  main.py
```

产物位于 `dist\SerialAssistant\`，双击其中的 `SerialAssistant.exe` 即可运行。
建议直接分发整个目录（onedir 模式启动更快，也更容易排查问题）。

如需单文件 exe：

```powershell
pyinstaller --noconfirm --windowed --onefile --name SerialAssistant `
  --exclude-module PySide6.QtWebEngineCore `
  --exclude-module PySide6.QtWebEngineWidgets `
  --exclude-module PySide6.QtPdf `
  main.py
```

> 单文件模式每次启动都会解压运行时文件，启动稍慢，且部分杀毒软件可能误报。
> 如需自定义图标，追加 `--icon app.ico` 参数。

## 生成安装程序（Setup.exe）

项目已附带 Inno Setup 脚本 `setup.iss`，可生成可执行的 Windows 安装程序（含开始菜单、桌面快捷方式、卸载入口）。

1. 先按上面的步骤用 PyInstaller 生成 `dist\SerialAssistant\` 分发包。
2. 安装 [Inno Setup](https://jrsoftware.org/isdl.php)（winget：`winget install JRSoftware.InnoSetup`）。
3. 在项目目录运行：

```powershell
& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" setup.iss
# 若通过 winget 安装到用户目录，路径通常为：
# & "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe" setup.iss
```

编译产物：`dist\SerialAssistant-Setup-v1.0.0.exe`，双击即可运行安装向导；安装后可在「设置 → 应用」中卸载，或运行安装目录下的 `unins000.exe`。

> 预编译的安装包请到 [Releases](https://github.com/junyu463/serial-assistant/releases) 页面下载 `SerialAssistant-Setup-v1.0.0.exe`。

## 使用说明

- 程序启动时会自动扫描串口，点击「刷新串口」可重新扫描；串口号也支持手动输入，例如 `COM5`。
- 修改串口参数（波特率、数据位、停止位、校验位、流控）前需先关闭串口。
- 文本模式按 GBK 编码收发；HEX 模式接收按每行 16 字节显示，发送支持空格 / 逗号分隔与 `0x` 前缀。
- 勾选「覆盖接收」后，新收到的数据会替换接收区内容；不勾选则持续追加。
- 「暂停接收」仅暂停界面刷新，串口数据仍在后台读取并累计字节数，恢复后会一次性补显。
- 「定时发送」需要先打开串口，间隔单位为毫秒；串口异常断开时定时器会自动停止。
- 「保存数据」导出的是接收区当前显示内容（文本模式为 GBK 解码后的文本，HEX 模式为十六进制字符串），文件编码为 UTF-8。
- 部分 USB 转串口驱动不支持 1.5 停止位或 Mark / Space 校验，此时打开串口会给出对应错误提示。

## 无硬件时的测试建议

可安装虚拟串口对（如 com0com）创建一对互联的虚拟串口，或用 USB-TTL 模块将 TX 与 RX 短接做回环测试。

## 许可证

本项目采用 [MIT License](LICENSE)。
