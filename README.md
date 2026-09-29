# reBotArm Studio

reBotArm Studio 是面向 reBotArm 多产品线的桌面控制与数字孪生应用。

首个支持的产品是 **B601-RS**。仓库从第一天起按产品注册表组织，后续可以加入
**B601-DM**，用户在同一个 App 内选择产品，而不需要维护两套桌面程序。

## 项目目标

- 最终用户不需要安装 ROS 2、colcon 或 rosbridge；
- 完整保留真机的控制、安全、轨迹、示教和重力补偿能力；
- 使用 MuJoCo WebAssembly 在 App 内完成仿真；
- 真机和仿真使用同一套 `RobotClient` 协议；
- RS、DM 的差异由产品描述和驱动适配器承载，不散落在 UI 中；
- ROS 2 兼容若有需要，作为仓库外的可选桥接层提供。

## 当前状态

RS 的第一阶段本地适配已经完成：控制核心和 RobStride SDK 已移入仓库，`rebotd`
直接通过 SocketCAN 管理真机，不依赖 ROS 2；旧版真机控制页面已经接入新的 WebSocket
协议；MuJoCo WASM 数字孪生也已迁入同一个前端。

| 产品 | 状态 | 计划后端 |
|---|---|---|
| B601-RS | `supported` | RobStride + SocketCAN |
| B601-DM | `planned` | Damiao + Serial CAN bridge |

B601-DM 保留产品入口，等硬件驱动和模型验证完成后再标记为可用。

## 目录

```text
apps/desktop/             Electron 桌面壳
frontend/app/             产品选择与控制 UI
frontend/robot-client/    真机/仿真统一客户端
frontend/web-mujoco/      MuJoCo WASM 仿真
backend/src/rebotd/       真机控制守护进程
products/                 RS、DM 产品声明和产品资源入口
protocol/                 跨进程协议及 TypeScript 类型
assets/                   经审核后迁入的共享资源
packaging/                Electron、Python、Linux 打包配置
docs/                     架构与迁移文档
tests/                    协议、真机和兼容性测试
```

## 本地运行（不连接真机）

需要 Python 3.10–3.12、Node.js 20+：

```bash
./scripts/bootstrap.sh
./scripts/dev.sh
```

浏览器打开：

- 数字孪生：<http://127.0.0.1:5173>
- RS 控制台：<http://127.0.0.1:5173/rs-console/index.html>

默认以未连接状态启动。页面会自动连接本地控制服务，但不会自动连接或驱动机械臂。
需要完整测试控制功能而不操作真机时使用：

```bash
./scripts/dev.sh --fake
```

运行全部本地测试：

```bash
./scripts/test.sh
```

## 在 App 内连接真机

先检查 Python 依赖、资源和 SocketCAN：

```bash
./scripts/doctor.sh can0
```

打开 RS 控制台后，在页面内完成以下操作：

1. 点击“扫描 CAN”，选择检测到的 PCAN / SocketCAN 接口；接口未启动时，App 会在连接阶段自动配置为 1 Mbps；
2. 清空工作区、卸下负载并勾选安全确认；
3. 点击“连接机械臂”，再次确认后由 `rebotd` 独占 CAN；
4. 核对六轴反馈，再单独开启网页控制锁和使能。

连接会让电机进入当前位置保持，可能产生轻微运动，因此 App 不会自动连接真机。点击
“安全断开”时，控制服务会停止重力补偿，并在需要时安全回零、失能后释放 CAN。
如果系统尚未授予 CAN 网络配置权限，连接时会自动弹出一次系统图形授权窗口；批准后
App 会继续配置接口，不需要执行终端命令。
开发阶段只需运行一次 `./scripts/dev.sh` 启动前后端；正式桌面包会由 Electron 自动
启动和监督 `rebotd`，最终用户不需要打开终端。
当前阶段只做本地运行与测试，桌面 App 打包将在真机验收后进行。

## 设计文档

- [总体架构](docs/ARCHITECTURE.md)
- [多产品模型](docs/PRODUCT_MODEL.md)
- [迁移路线](docs/MIGRATION.md)
- [本地协议](docs/PROTOCOL.md)
- [RS 真机验收清单](docs/RS_HARDWARE_ACCEPTANCE.md)

## 发布与许可

本仓库在完成第三方代码、SDK 和模型资产许可审计前不发布二进制包。详见
[NOTICE.md](NOTICE.md)。
