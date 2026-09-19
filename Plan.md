# Plan: Art-Net Light (HA custom integration)

> 活文档：每完成/变更一项就更新状态。设计取舍记录在 [DECISIONS.md](DECISIONS.md)。
> 最近更新：2026-09-19

## 目标
HACS 可安装的 Home Assistant 自定义集成 `artnet_light`：
- 自动发现局域网 Art-Net 节点（ArtPoll），也可手动添加
- 全部配置走 HA 原生 UI（Config Flow + Options Flow），无 YAML
- 在选项流里增/改/删灯具，实体立即生效，无需重启 HA

## 需求（采访确认）
| 项 | 决定 |
|---|---|
| 自动发现 | 添加集成时扫描下拉选择 + 后台周期扫描弹“已发现”卡片（D-003） |
| 配置条目粒度 | 1 条目 = 1 节点(IP+端口)，节点下多个 Universe，添加灯具时选 Universe（D-002） |
| 通道精度 | 每灯具可选 8 / 16 位 |
| CCT | 冷/暖两路 或 亮度+色温 两种都支持 |
| 发送策略 | 选项可配：变化即发+保活 / 固定帧率连续发送 |
| 渐变 | 支持 `transition` + 默认渐变时间 |
| 重启恢复 | RestoreEntity 恢复并立即重发 |
| 分发 | HACS，最低 HA 2024.11，中英翻译 |

## 交互流程
1. **添加集成**：扫描 3 秒 → 下拉列出节点 + “手动输入” → 手动填 IP/广播地址、端口(6454)、名称
2. **后台发现**：已有条目时每 5 分钟 ArtPoll，新节点 → `integration_discovery` 卡片 → 确认添加
3. **选项菜单**：➕ 添加新灯具 / ✏️ 修改或删除灯具 / ⚙️ 发送设置
4. **灯具表单**：名称、类型、Universe、起始通道、8/16 位；「高级参数」折叠区：通道顺序、CCT 模式、色温范围、最小/最大输出
5. 保存 → 重载条目 → `light.ke_ting_deng_dai` 立即出现

## 进度

### 已完成（v0.1.0）
- [x] `artnet.py` 协议层：ArtDmx / ArtPoll / ArtPollReply 构建与解析
- [x] `fixture.py` 灯具模型：通道布局、状态→电平→DMX 编码、重叠检测
- [x] `controller.py` 发送器：Universe 缓冲、两种发送模式、渐变
- [x] `discovery.py` 扫描 + 后台发现
- [x] `config_flow.py` 配置流 + 选项流（校验：溢出/重叠/通道顺序/范围）
- [x] `light.py` 实体（每灯具一个设备，via_device 挂节点）
- [x] 中英翻译、manifest、hacs.json、README
- [x] `tests/test_core.py` 21 项通过（本机 Python 3.11）
- [x] `tools/fake_node.py` 模拟节点，本机回环验证通过
- [x] CI 工作流：hassfest + HACS validate + pytest

### 待办
- [x] 在 Linux 上运行 `tests/ha/test_flows.py`：py3.13/HA 2026.2.3 与 py3.14/HA 2026.9.2 均通过（v0.1.1 修复了 2 个问题）
- [x] 真实 HA 端到端验证（HA 2026.9.2 + 模拟节点）：发现、添加节点、添加灯具、颜色/亮度/渐变/关灯、重启恢复并重发、设备归属（v0.1.2）
- [ ] 在真实界面里走一遍（目前是通过 REST API 驱动的）：手动添加路径、修改/删除灯具、发送设置、CCT/RGBW/16 位灯具
- [x] git 仓库初始化，v0.1.0 已提交并打 tag
- [ ] 推到 GitHub，跑通 CI；替换 manifest 中的占位 URL 与 codeowners
- [ ] 关灯状态下重启会丢失上次亮度/颜色（HA 关灯态不带这些属性）→ 考虑 `ExtraStoredData`
- [ ] （可选）接真实 Art-Net 节点 / QLC+ 监视验证

## 验证方法
1. `pytest tests/test_core.py -p no:homeassistant` —— 协议字节、灯具换算、发送器（本机即可）
2. `pytest tests/ha`（在 Linux 测试机 192.168.1.167 的一次性 python:3.14 容器里跑，命令见 CLAUDE.md）—— 配置流/选项流/实体
3. 局域网另一台电脑跑 `tools/fake_node.py`，HA 里添加集成，观察打印的 DMX 值
