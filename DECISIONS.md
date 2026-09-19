# 决策记录 (Decision Log)

轻量 ADR：每条记录 背景 → 决定 → 理由/代价。新决策追加到末尾，编号递增；被推翻的决策标记为「已废弃」并指向新条目，不删除。

---

## D-001 协议层自研，不依赖第三方库
- **日期**：2026-09-19 · **状态**：采纳
- **背景**：可用 `pyartnet` 等库；但发现功能需要 ArtPoll/ArtPollReply，库不一定覆盖。
- **决定**：`artnet.py` 用纯 asyncio + struct 实现，`manifest.json` 的 `requirements` 为空。
- **理由/代价**：HACS 安装零依赖、无版本冲突；需自己维护包格式（Art-Net 4 协议稳定，量小）。

## D-002 一个配置条目 = 一个节点，多 Universe；Universe 在灯具上指定
- **日期**：2026-09-19 · **状态**：采纳
- **背景**：原始需求是在添加集成时填 Universe；用户确认一个网关可能有多个输出口。
- **决定**：条目 `data` = host/port/name/mac/universes（节点上报的 Universe 列表）；每个灯具自带 `universe` 字段，默认取节点上报的第一个，没有则 0。
- **理由/代价**：贴合多口网关；和最初描述的 UI 不同，添加集成时不再询问 Universe。

## D-003 发现：添加时扫描 + 后台周期扫描
- **日期**：2026-09-19 · **状态**：采纳
- **决定**：`async_step_user` 扫描 3 秒给下拉；`async_setup` 里每 5 分钟（启动后 30 秒首次）扫描并用 `discovery_flow.async_create_flow(... SOURCE_INTEGRATION_DISCOVERY)` 弹卡片。
- **限制**：HA 仅在已有条目时加载集成，第一个节点只能靠添加时的扫描/手动输入。已写入 README。
- **去重**：unique_id 优先 MAC（`format_mac`），无 MAC 用 IP；手动条目 unique_id 为 `host:port`，另用 `_async_abort_entries_match({host})` 防止与发现结果重复。节点 IP 变化时通过 `updates={host}` 自动更新。

## D-004 灯具存在 `entry.options["fixtures"]`，改动后整条目重载
- **日期**：2026-09-19 · **状态**：采纳
- **背景**：需求“保存后立即生效，无需重启”。可选方案：动态增删实体 vs 重载条目；HA 2025.x 的 config subentries 也可用，但用户指定选项流菜单，且要兼容 2024.11。
- **决定**：update listener 调 `async_reload`；`setup_entry` 时清理已删除灯具的实体/设备注册项。灯具用 uuid 作 unique_id，改名不丢实体。
- **理由/代价**：实现简单可靠；重载时新控制器缓冲为 0，靠“实体恢复完再开始发送”（`async_start_sending` 在 platform setup 之后调用）避免闪烁。

## D-005 每个灯具是独立设备（via_device 挂在节点下）
- **日期**：2026-09-19 · **状态**：采纳
- **背景**：`has_entity_name=True` 时，若实体挂在节点设备上，entity_id 会是 `light.<节点名>_<灯具名>`，与需求示例 `light.ke_ting_deng_dai` 不符。
- **决定**：每个灯具建一个设备，实体 `name=None`，entity_id 由灯具名生成（中文经 unidecode 转拼音）。

## D-006 电平在浮点空间计算，编码最后一步做
- **日期**：2026-09-19 · **状态**：采纳
- **决定**：`Fixture.compute_levels()` 输出 0.0–1.0 电平（已套最小/最大输出，`T` 色温通道不套），`encode()` 再转 8/16 位字节。渐变在浮点电平上插值。
- **理由**：16 位的高/低字节不能分别插值；统一的电平表示让渐变、限幅、通道顺序互不干扰。

## D-007 通道顺序用字母串表示
- **日期**：2026-09-19 · **状态**：采纳
- **决定**：R G B / W(暖白) / C(冷白) / I(亮度) / T(色温)。默认：dimmer `I`、CCT `CW` 或 `IT`、RGB `RGB`、RGBW `RGBW`、RGBWW `RGBCW`。输入必须是默认值的排列，留空为默认。
- **代价**：修改灯具类型时，之前自定义的顺序可能不再合法，需用户清空（表单会报 `invalid_order`）。

## D-008 发送模式两种，由选项配置
- **日期**：2026-09-19 · **状态**：采纳
- **决定**：`on_change`：变化立即发脏 Universe，另每 `keepalive` 秒全量重发；`continuous`：按 `fps`（1–44）全量发送。总是发送完整 512 字节。
- **理由**：兼顾低流量与对“无数据超时熄灭”节点的兼容性。

## D-009 核心模块不导入 Home Assistant
- **日期**：2026-09-19 · **状态**：采纳
- **背景**：开发机是 Windows + Python 3.11，无法安装 HA（需 3.12+、推荐 Linux）。
- **决定**：`artnet.py` / `fixture.py` / `controller.py` / `const.py` 只用标准库；测试通过伪包名 `artnet_core` 直接加载它们，绕过包的 `__init__.py`。HA 相关测试放 `tests/ha/`，在 CI（Ubuntu, Py3.13）上跑。
- **约束**：以后给这些模块加 HA 导入会破坏本地测试和 `tools/fake_node.py`。

## D-010 版本管理：每次代码修改自动提交并打 tag
- **日期**：2026-09-19 · **状态**：采纳
- **背景**：个人开发者 + agent 主力开发，需要可追溯、可回滚的版本；HACS 按 git tag 识别版本。
- **决定**：
  - SemVer：patch = 修复/重构，minor = 新功能/新选项，major = 存储配置不兼容（需写 config entry 迁移）。
  - `manifest.json` 的 `version` 是唯一版本来源，必须与 tag `vX.Y.Z` 一致。
  - 每次代码修改完成后，由 agent 自动执行：改版本号 → 更新 `CHANGELOG.md` / `Plan.md` → 跑核心测试 → 一个提交（Conventional Commits 前缀）→ 打附注 tag。
  - 纯文档改动只提交（`docs:`），不升版本、不打 tag。
  - 直接在 `main` 上提交；push / 创建远程或 Release 需先征得同意。
