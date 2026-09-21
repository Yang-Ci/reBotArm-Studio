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

这是新 App 仓库的初始架构骨架：

| 产品 | 状态 | 计划后端 |
|---|---|---|
| B601-RS | `supported` | RobStride + SocketCAN |
| B601-DM | `planned` | Damiao + Serial CAN bridge |

目前尚未复制旧仓库的控制代码和模型资源。下一阶段会先迁移 RS 无 ROS 控制核心，
并建立与旧 ROS 版本的行为等价测试。

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

## 验证产品注册表

需要 Python 3.11：

```bash
python3.11 -m unittest discover -s backend/tests -v
PYTHONPATH=backend/src python3.11 -m rebotd products list
```

也可以使用当前系统 Python 运行不依赖第三方库的注册表测试：

```bash
python3 -m unittest discover -s backend/tests -v
PYTHONPATH=backend/src python3 -m rebotd products list
```

## 设计文档

- [总体架构](docs/ARCHITECTURE.md)
- [多产品模型](docs/PRODUCT_MODEL.md)
- [迁移路线](docs/MIGRATION.md)

## 发布与许可

本仓库在完成第三方代码、SDK 和模型资产许可审计前不发布二进制包。详见
[NOTICE.md](NOTICE.md)。
