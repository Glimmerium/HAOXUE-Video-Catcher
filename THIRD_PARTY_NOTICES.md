# 第三方组件与分发说明

本仓库的 MIT 许可证仅覆盖作者原创代码和文档，不改变第三方组件的许可。
本文件是组件索引，不替代各组件完整许可证，也不代表已完成某个 EXE 的再分发审查。

| 组件 | 用途 | 上游说明 |
| --- | --- | --- |
| Python / Tkinter / Tcl/Tk | 程序运行与窗口界面 | [Python 许可证](https://docs.python.org/3/license.html)，Tcl/Tk 的声明见实际运行库分发文件 |
| imageio-ffmpeg | 定位和提供 FFmpeg 程序 | [上游仓库与许可证](https://github.com/imageio/imageio-ffmpeg)；其 Python 包与 FFmpeg 二进制的许可须分别处理 |
| FFmpeg | 解密、解复用及 MP4 封装 | [官方许可说明](https://ffmpeg.org/legal.html)；具体 LGPL/GPL 条件取决于实际构建选项与依赖 |
| PyInstaller | Windows EXE 打包 | [许可证及引导程序例外](https://pyinstaller.org/en/stable/license.html) |
| BlueStacks / HD-Adb | 安卓模拟器与本机文件传输 | 外部安装，本源码仓库不包含其安装包或程序；适用原供应商条款 |
| 北大好学 APP | 用户自行下载课程的来源 | 外部安装，本源码仓库不分发 APK、课程或密钥 |

## 发布源码

保留 LICENSE、ASSETS_LICENSE.md 和本文件。课程内容、账号信息、密钥、模拟器镜像和第三方安装器不应进入源码仓库。

## 发布 EXE

打包脚本会将 FFmpeg 和 Python 界面运行库带入 EXE。发布者需按实际产物：

1. 记录 Python、Tcl/Tk、imageio-ffmpeg、PyInstaller 和 FFmpeg 的版本；保存 FFmpeg 的 `-version`、`-buildconf`、`-L` 输出。
2. 随发行包提供上述组件适用的完整许可证和版权声明，以及本项目许可证和标识说明。
3. 按实际 FFmpeg 构建的许可证落实对应源码及构建信息的提供要求；仅链接 FFmpeg 首页不等于已履行这些要求。
4. 将准备完整的发行包上传 GitHub Releases；不要把历史同学分享包中的 APK 或模拟器安装器默认视为本项目可重新授权的内容。

当前仓库中的说明适用于源码发布。历史生成的 EXE/分享包未在此次操作中重新打包或补齐第三方许可证附件。
