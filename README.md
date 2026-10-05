# CE5221：本地交通视频分析

目标：评价中国某信号交叉口的机动车和行人服务水平。此工具实现 **OpenCV 读取视频 → YOLO 检测 → ByteTrack / BoT-SORT 跟踪 → 交通事件提取 → CSV 汇总**。视频在自己的电脑运行，代码和经复核的汇总结果可保存到 GitHub。

## Windows + NVIDIA：在 VS Code 中部署与导入视频

代码尚在开发分支时，首次下载：

```powershell
git clone --branch feature/local-traffic-analysis https://github.com/Sxaliver/5221-Term-Project-LOS.git
cd 5221-Term-Project-LOS
code .
```

已有该分支的本地副本则直接 `git pull`。在 VS Code 中打开**仓库根目录**，安装推荐的 Python 扩展。先准备官方 Python 3.12（包含 Python Launcher 与 Tcl/Tk）及可用的 NVIDIA 显卡驱动；在终端中 `py -3.12 --version` 和 `nvidia-smi` 应能运行。

通过菜单 **Terminal → Run Task（终端 → 运行任务）** 按顺序选择：

1. **Traffic: Deploy NVIDIA GPU**：建立项目独立 `.venv`，检查驱动支持的 CUDA，安装对应 GPU 版 PyTorch、下载 `models/yolo11n.pt`，运行测试及真实 GPU 推理/跟踪自检。只有成功后才保存 `.local/deployment.json`。首次下载 PyTorch 及其 GPU 依赖需要数 GB 空间。
2. **Traffic: Annotate video**：文件选择窗口导入本机 MPG/MP4，自动打开标注页面。标注后把下载的 `scene.json` 保存到 `configs/`。
3. **Traffic: Pilot (2 min)**：依次选择视频和标注 JSON，用已验证的 GPU 配置分析前两分钟，生成复核录像和 CSV；每次试运行用独立输出目录，便于调整标注再比较。
4. **Traffic: Analyze full video**：复核后选择完整视频和同一 JSON，处理完整录像；同参数已完成文件可跳过，中断的视频保留结果后重跑。

也可在 VS Code PowerShell 终端先执行一条部署命令，无需手动激活虚拟环境：

```powershell
py -3.12 tools\bootstrap_local.py --accelerator cuda
```

脚本依据驱动的 CUDA 支持选择官方 `cu128` 或 `cu126` 安装源，并为旧架构优先选择 `cu126`。不需要另行安装系统 CUDA Toolkit。若驱动过旧、显卡架构不受支持或 GPU 推理失败，会明确报错；不会静默改为 CPU 成功。部署失败后的旧成功标记会失效。

VS Code 任务固定使用项目 `.venv`。调试功能（F5）请通过 **Python: Select Interpreter** 选择 `.venv\Scripts\python.exe`；已有工作区曾选过其他解释器时，默认设置不会覆盖那次选择。

原始视频可以保留在任意本地磁盘，不需上传或复制进项目。文件选择框不可用时，可显式传入路径：

```powershell
.venv\Scripts\python.exe tools\run_video.py --mode pilot --video "D:\Videos\JF Ave-TJ St_1.MPG" --scene configs\jf_tj.scene.json
```

结果位于 `runs/vscode-pilot-<时间>/` 或 `runs/vscode-full/`。全片分析若修改配置、模型或版本，请用后文 CLI 的新 `--output` 目录，避免混用不同分析结果。`Traffic: Deploy CPU` 是显式的备用选项；选择后会重新验证 CPU 并记录 CPU 配置，不代表 GPU 部署完成。

当前云端任务不能直接执行你本机的 VS Code 命令；Windows/GPU 是否就绪，以本机部署任务输出的 `READY: device=0`、实际 `model_device=cuda:0` 和本机视频试运行结果为准。

## 已实现与测量边界

| 输出 | 用途 | 边界 |
|---|---|---|
| 分类别、分方向越线计数 | 机动车通过量、行人过街量 | 依赖计数线位置、跟踪连续性和人工抽查 |
| entry → exit 配对 | 按进口、出口判断左转/直行/右转 | 用相同 ID 配对；未看见进口或发生 ID 切换的对象不配对 |
| 越线车头时距 | 放行时间间隔候选样本 | 只有车道级停车线、持续排队放行阶段才能用于饱和时距 |
| 区域可见对象数及均值/最大值 | 查看等待区或车道区域占用 | **不是**静止队列、排队长度、车辆密度或行人等待时间 |
| 轨迹、事件和元数据 | 复核、后续延误与信号分析 | 像素坐标未经距离标定，不输出实际速度和米数 |

目前不自动输出信号配时、饱和流率、行人完整等待时间、机动车控制延误或 LOS 等级。它们需要信号相位、场景几何、轨迹完整性验证及所选计算标准。不要把通过量等同于拥堵时的到达需求，也不要将区域人数直接当作行人延误。

## 1. 安装（推荐 Python 3.12）

先克隆仓库并进入目录；已有本地副本则直接使用。视频放在 `data/` 中，不上传 Git。

```bash
git clone https://github.com/Sxaliver/5221-Term-Project-LOS.git
cd 5221-Term-Project-LOS
python -m venv .venv
```

激活环境：

- Windows PowerShell：`.venv\Scripts\Activate.ps1`（若系统禁止激活，可直接用 `.venv\Scripts\python.exe` 替代下文的 `python`）。
- macOS / Linux：`source .venv/bin/activate`。

Linux / Windows 使用 CPU 的安装方式：

```bash
python -m pip install torch==2.9.0 torchvision==0.24.0 --index-url https://download.pytorch.org/whl/cpu
python -m pip install -e ".[test]"
python -m pytest -q
```

macOS：先用 `python -m pip install torch==2.9.0 torchvision==0.24.0`，再执行上面的项目安装与测试。Apple 芯片可尝试 `--device mps`，CPU 可作为兼容性回退。

NVIDIA GPU：依据 [PyTorch 官方安装说明](https://pytorch.org/get-started/locally/) 安装与驱动兼容的 torch/torchvision（此项目测试组合为 2.9.0 / 0.24.0），再安装本项目，分析时使用 `--device 0`。不要同时混装不同 CUDA/CPU 版本。

首次使用 `yolo11n.pt` 会下载官方模型，需要访问 GitHub release assets。也可以预先下载权重并使用 `--model models/yolo11n.pt`。运行元数据记录权重 SHA-256 和软件版本。Ultralytics 的开源许可为 AGPL-3.0，使用和再分发时应遵守其许可。

## 2. 根据自己的视频标注

```bash
python -m traffic_los.cli annotate "data/JF Ave-TJ St_1.MPG" --at 30 --output scene-annotator.html
```

在本地浏览器打开生成的 `scene-annotator.html`，无需服务器或联网。它内嵌选定帧，可以点击标注并下载 `scene.json`。将 JSON 保存到 `configs/jf_tj.scene.json`。

标注建议：

1. 每个进口设置一条 `entry` 线，每个出口设置一条 `exit` 线，避免同一车辆经过多条不同进口线。进口与出口都应位于清楚可见的位置。
2. 按进口和出口方向解释转向，例如 `north_entry → south_exit` 是从北向南行驶，通常为直行。程序保留原配对，不猜测真实地理方向。
3. 需要车头时距时，每条车道单独设置停车线 `count`，不要跨多条车道混合测量。
4. 行人横道设置 `count`，类别填 `person`，方向选择 `both`；统计的是穿越该线的轨迹，不是每一帧的人数。
5. 等待区、车道区域可以画多边形 `zone`，并用类别筛选：行人等待区用 `person`，车辆观察区用 `car,bus,truck,motorcycle`。未设置类别的旧配置仍统计所有启用类别。可见对象数不能自动判断对象是否在排队。

### JF Ave–TJ St 专用标注模板

依据视频说明文档，页面提供主路进口／出口、车道停止线、JF 左转待转区、渠化右转进口／出口、主路行人过街、右转支路行人过街、行人等待区和车道观察区模板。模板只提供类型、类别和提示，不预置未经确认的像素坐标。

- 先核对道路和行驶方向。`JF_EB` 表示沿 JF Ave 向东行驶，并不表示画面右侧；主路行人模板中的道路表示过街路径平行于哪条道路。
- 画完两端点，点击 **点击驶向侧选择方向**，再在车辆穿线后驶向的一侧点击一次；这次点击不增加端点。核对穿越箭头，再点击 **添加标注**。行人双向过街保留 **两个方向**。
- JF 内侧左转待转区应单独画区域，进口计数线放在其上游。进入待转区可能发生在直行阶段，不能当作完成左转；最终转向仍用进口到出口的轨迹配对。
- 渠化右转车道分流后独立画进口／出口线，避免和主路进口线重复计数。右转支路人行横道单独计数，不套用主路行人信号阶段。
- 使用列表中的 **编辑／删除** 调整标注，或 **导入已有 scene.json** 继续修改；导入必须匹配原图分辨率。保存时若有红色草稿，需先添加或清除。关闭页面前下载 JSON，页面不会自动保存。

配置保留 `purpose`、`road`、`heading`、`phase_group` 说明字段，仍兼容 schema_version 1 的分析程序。阶段标签不代表自动信号识别或实际时间序列。图纸中的 11.20、33.60、18.20、20.0 m 是断面参考尺寸，不直接作为透视图像素比例；本功能没有自动计算延误、排队长度或 LOS。

线有两个端点 A、B，图上 `+` 标记表示叉积为正的一侧。`positive` 表示从负侧穿向正侧，`negative` 表示反向。注意画面坐标 y 向下。默认三像素死区用于减少线边抖动；对象脚点/车辆框底边中心作为地面锚点。

`configs/scene.example.json` 只有演示坐标，**不能直接用于你的路口**。视频分辨率与标注帧不匹配时程序会报错；重新标注，不会隐式缩放坐标。

## 3. 先跑两分钟并复核

```bash
python -m traffic_los.cli analyze "data/JF Ave-TJ St_1.MPG" --scene configs/jf_tj.scene.json --duration 120 --overlay-seconds 120 --output runs/pilot --device cpu
```

检查输出的 `overlay.mp4`：是否漏检、重复计数、ID 切换、转向配对失败，线是否放在遮挡区域。对照人工统计，分别报告各类别/方向的计数误差和完整轨迹比例。先验证拥堵、行人密集和转弯冲突片段，再处理全部数据。

可试 `--tracker botsort` 与默认的 `bytetrack` 比较。BoT-SORT 采用 Ultralytics 自带默认配置，不等同于已启用外观 ReID；固定机位下不保证比 ByteTrack 更准确。小目标识别可尝试 `--model yolo11s.pt --imgsz 1280`，代价是速度更慢。

## 4. 处理三小时或批量视频

```bash
python -m traffic_los.cli analyze data/ --scene configs/jf_tj.scene.json --output runs/full --device cpu --resume
```

也可在 `analyze` 后列出多个文件。NVIDIA GPU 使用 `--device 0`。默认保留原始帧进行跟踪，不通过跳帧加速；`--track-sample-seconds 0.5` 仅减少轨迹 CSV 写入量，不影响计数时使用的帧。

- 逐帧读取并流式写入，内存不随视频帧数线性增长。每十秒打印处理进度；CPU 处理三小时视频可能需要更长时间，以短样本的实际处理 FPS 估算。
- 视频按文件独立跟踪、独立计时，时间从各文件起点计算。程序不假设文件时间连续，不将各文件自动拼成一个高峰小时。
- `--resume` 跳过配置、输入文件大小/修改时间、权重哈希和软件版本相同的已完成文件。
- **未完成的视频从头重跑**；原 `.partial` 目录会改名保存用于审计。不恢复追踪器内存，不宣称任意帧断点恢复，也不静默拼接不同运行的 ID。
- 同一输入在参数变化后请使用新的 `--output`，避免覆盖旧结果。
- 视频无法解码或提前结束时，保留部分输出并报错；不会将其标记为完成。对于帧数元数据异常的 MPG，可用 FFmpeg 转为稳定帧率 MP4 后重新标注和运行，并记录转换方式。
- 默认 `--max-gap 1`：计数线两侧可靠观察相隔超过一秒时不推断穿越；严重遮挡可能造成漏计。每个 ID 每条线最多计数一次，适用于单次通过路口，不适合往返多次的行人研究。

## 输出文件

每个视频对应 `runs/full/<文件名>_<路径哈希>/`：

| 文件 | 内容 |
|---|---|
| `tracks.csv` | 采样轨迹，帧号、时间、ID、类别、置信度、框和锚点像素坐标 |
| `events.csv` | 插值越线时刻、越线方向、进口→出口事件；ID 只在本视频内唯一 |
| `headways.csv` | 每条线每个方向，相邻机动车的越线间隔；未筛选饱和放行阶段 |
| `summary.csv` | 默认 900 秒区间的分类计数、方向和进口→出口配对 |
| `occupancy.csv` | 约每秒一次的区域可见对象数，包含零计数 |
| `occupancy_summary.csv` | 同区间的区域占用均值、采样最大值和样本数 |
| `metadata.json` | 参数、输入指纹、模型哈希、软件版本、解码帧数、观测时长和完成状态 |
| `overlay.mp4` | 仅指定 `--overlay-seconds` 时生成的复核录像 |

`summary.csv` 中 `crossing` 与 `movement` 是两类事件，不要相加当作车辆总数。车头时距不能直接当作饱和时距。区间结束可能是部分区间，使用 `observed_end_s` 判断实际覆盖；不要将不足 15 分钟的数据直接视为完整 15 分钟交通量。配置线路输出零计数行；从未出现过的进口→出口配对不自动输出零值，不代表已完整观测到该转向。

时间优先使用 OpenCV 解码时间戳，起点异常时使用 `frame_index/fps`；实际选择记录在元数据。后一种方式只适用于稳定帧率输入。两个途径都不恢复真实日期；需要结合录像开始时间人工添加绝对时间。轨迹 ID 跳变、检测类别跳变和遮挡仍可能影响统计，CSV 不代表已经过人工核验。

## 5. 将复核后的汇总保存到 GitHub

原始视频、权重和 `runs/` 默认忽略。推荐只保存小体积的汇总、标注和方法说明：

```bash
python -m traffic_los.cli export runs/full --output results/jf_tj
git add results/jf_tj configs/jf_tj.scene.json
git commit -m "Add reviewed intersection traffic summaries"
git push
```

`export` 只复制已完成运行的汇总和元数据，将机器上的绝对路径改为文件名。导出并不代表数据已经复核；请在 `results/jf_tj/NOTES.md` 记录录像时段、人工误差检查、遮挡限制、标注方法及分工。原始事件、轨迹和复核视频保留本地；后续分析需要它们时再单独管理。

## 测试与复现

```bash
python -m pytest -q
python -m pip check
```

自动测试覆盖有限线段穿越、方向和类别筛选、抖动、遮挡间隙、转向配对、输出分箱、已完成文件跳过、参数冲突和中断输出保留。真实 YOLO 的验证范围见 [验证记录](docs/VALIDATION.md)。模拟视频和公共样图验证不能替代你的监控视频精度检查。
