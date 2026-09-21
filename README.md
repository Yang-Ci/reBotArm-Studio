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

默认使用 fake RS 驱动，可以完整测试连接、使能、关节、轨迹、夹爪、IK、示教和重力补偿接口，不会操作真机。

运行全部本地测试：

```bash
./scripts/test.sh
```

## 真机开发模式

先检查 Python 依赖、资源和 SocketCAN：

```bash
./scripts/doctor.sh can0
```

确认机械臂周围安全、CAN 已配置后，显式确认并启动：

```bash
export REBOTARM_HARDWARE_CONFIRM=I_UNDERSTAND_REBOTARM_WILL_MOVE
./scripts/dev.sh --hardware
```

真机模式不会因为打开网页自动使能；仍需在控制台中连接、开启控制锁并手动使能。
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
