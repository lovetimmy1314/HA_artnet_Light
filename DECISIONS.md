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

## D-011 远程 Linux 测试机 + 核心/HA 测试分开跑
- **日期**：2026-09-19 · **状态**：采纳
- **背景**：本机跑不了 HA；HA 的 pytest 插件会禁用 socket、替换事件循环，和核心层的真实 UDP 测试冲突。
- **决定**：
  - HA 测试在 `root@192.168.1.167` 上的一次性 `python:3.14` 容器里跑（得到和线上一样的 HA 2026.9.x），必须加 `--network host`，因为 Docker 注入的代理在 127.0.0.1:20171。
  - `pytest.ini` 只收集 `tests/ha`；核心测试单独用 `-p no:homeassistant` 运行。CI 也拆成两步。
- **代价**：在同一次 `pytest` 里跑不了全部测试，需要跑两条命令。

## D-012 后台任务由宿主创建（发送器接受 task factory）
- **日期**：2026-09-19 · **状态**：采纳
- **背景**：用 `loop.create_task` 创建的发送循环 HA 不知道，关闭时不会被取消（在 HA 2026.9 的测试里报了 lingering task）。
- **决定**：`ArtNetController.async_start_sending(create_task=None)`；HA 层传入 `entry.async_create_background_task`。核心层仍然不导入 HA（D-009），不传参数时退回 `loop.create_task`，本地测试照常可用。
- **补充（v0.2.0）**：渐变任务也通过同一个 factory 创建。

## D-013 灯具设备在 setup_entry 中创建，用 via_device_id 挂到节点
- **日期**：2026-09-19 · **状态**：采纳（补充 D-005）；兼容 2024.11 的写法已废弃 → D-015
- **背景**：HA 2026.x 弃用了 `DeviceInfo(via_device=...)` / `async_get_or_create(via_device=...)`，2027.8 起失效；而 `async_get_or_create(via_device_id=...)` 在 2024.11 中还不存在。
- **决定**：`async_setup_entry` 先建节点设备，再为每个灯具 `async_get_or_create` 设备，然后 `async_update_device(via_device_id=node.id)`（这个接口一直都有）。实体的 `DeviceInfo` 只带 `identifiers`。
- **理由**：一套代码同时兼容最低版本和最新版本，不需要做版本判断。

## D-014 亮度/颜色用 ExtraStoredData 保存，关灯也不丢
- **日期**：2026-09-19 · **状态**：采纳
- **背景**：HA 关灯状态不带 brightness / rgb_color 等属性，只靠 `async_get_last_state()` 恢复时，关灯重启后再开灯会回到默认全亮白色。
- **决定**：实体实现 `extra_restore_state_data`，保存亮度、rgb/rgbw/rgbww、色温；恢复时优先用它，没有（0.1.2 及更早保存的状态）才退回读状态属性。开关状态仍取自 `last.state`。
- **理由/代价**：不改存储配置，无需迁移；每个实体在 `core.restore_state` 里多存几个字段。

## D-015 只适配最新版 HA（最低 2026.9）
- **日期**：2026-09-19 · **状态**：采纳（取代需求表里的“最低 HA 2024.11”）
- **背景**：审查时在 HA 2024.11.3 上跑测试，选项流直接报错（2024.11 的 `OptionsFlow` 不会自动注入 `config_entry`，2024.12 起才会）。声明的最低版本其实从没验证过。
- **决定**：用户确认只适配最新版。`hacs.json` 最低 2026.9.0，CI 和测试机都用 py3.14（解析到最新 HA）。可以直接用新 API：灯具设备用 `async_get_or_create(via_device_id=...)` 一步创建（原来为兼容 2024.11 先建再 `async_update_device`，见 D-013），平台回调类型用 `AddConfigEntryEntitiesCallback`。
- **代价**：老版本 HA 的用户无法安装；以后 HA 弃用接口时直接跟进，不再做版本判断。

## D-016 不再使用的 Universe 补发一帧全 0
- **日期**：2026-09-19 · **状态**：采纳
- **背景**：控制器只发送有灯具的 Universe。删掉某个 Universe 上最后一个灯具、把灯具改到别的 Universe、禁用或删除节点后，这个 Universe 不再发送，多数节点会保持最后一帧，灯一直亮着。
- **决定**：`async_unload_entry` 时对“旧控制器发送过、新选项里已没有灯具”的 Universe 立即补发一帧全 0（`controller.blackout`）；条目被禁用时全部补发。删除节点时，`async_remove_entry` 临时开一个 socket 对所有灯具的 Universe 补发。
- **理由/代价**：重载时仍在用的 Universe 不受影响，不会闪烁（D-004）。HA 正常关闭/重启不补发，灯保持原状态，重启后由恢复逻辑接管。只补发一帧，UDP 丢包时仍可能残留，可接受。

## D-017 灯具表单的错误分放三处，保证同时可见
- **日期**：2026-09-19 · **状态**：采纳
- **背景**：通道顺序、色温范围、输出范围三项校验原先都写到 `errors["base"]`，同时出错时只显示最后一个。这三个字段都在「高级参数」section 里，而 HA 前端不会把错误传进 section 内部的字段（`ha-form-expandable` 不传 `error`），按字段名挂错误不会显示。
- **决定**：通道顺序错误放 `base`（它和灯具类型共同决定，显示在表单顶部）；色温/输出范围错误挂在 section 名 `advanced` 上（前端在该 section 旁显示）；两者同时出错时用合并的错误文案 `invalid_kelvin_and_output_range`。
- **理由/代价**：不改表单结构即可让所有错误同时可见；代价是多一条组合文案，以后在 section 里再加校验项时需要同样处理。

## D-018 仓库公开，采用 Apache-2.0 许可证
- **日期**：2026-09-19 · **状态**：采纳
- **背景**：CI 的 HACS 检查一直失败：私有仓库下 hacs/action 读不到 `hacs.json` 和 manifest（报 `Got None`），另外还缺 LICENSE 和 topics。HACS 本身也只能安装公开仓库。
- **决定**：GitHub 仓库改为公开；添加 Apache-2.0 LICENSE（与 Home Assistant 一致）；topics 设为 hacs / home-assistant / homeassistant / hacs-integration / artnet / dmx。CI 仍然跳过 brands 检查。
- **理由/代价**：公开后 CI 全绿，可通过 HACS 自定义存储库安装。代价：`CLAUDE.md`、`Plan.md` 及其历史中的内网测试机地址、容器名一并公开（均为局域网私有地址，未包含任何凭据）。

## D-019 CI 只在代码/版本变动时触发
- **日期**：2026-09-19 · **状态**：采纳
- **背景**：纯文档提交（Plan/DECISIONS/README/CLAUDE.md）也会跑一遍 CI，白白消耗 Actions 时间。
- **决定**：`push` 只看 `main` 分支和 `v*` tag，分支推送用 `paths` 过滤：`custom_components/`、`tests/`、`tools/`、`hacs.json`、`requirements_test.txt`、`pytest.ini`、`.github/workflows/`；PR 用同一组路径（YAML 锚点复用）。tag 推送不受 `paths` 限制，每个版本都会跑。
- **理由/代价**：文档改动不再触发 CI；代价是 README 改动不会重新跑 HACS 检查（README 不在它的检查项里），新增代码目录时要记得加进路径列表。

## D-020 节点地址用 Reconfigure 修改；选项流改用 OptionsFlowWithReload
- **日期**：2026-09-19 · **状态**：采纳（D-004 的重载方式由此改变）
- **背景**：节点换 IP 后只能删掉重加，灯具配置会全部丢失。另外，条目上挂的更新监听器会在任何条目更新时重载；HA 2026.9 对「有更新监听器的条目又由流程触发重载」报弃用警告（2026.12 起会失效），自动发现更新 IP 时已经触发这个警告，新加的 Reconfigure 也会触发。
- **决定**：新增 `async_step_reconfigure`，可改 host / port / name，用 `async_update_reload_and_abort` 保存。自动发现的节点保留 MAC 唯一 ID；手动节点的唯一 ID 改为新的 `host:port`。与其他条目的唯一 ID 或 host+port 冲突时，在表单里提示 `already_configured`，不直接中止。节点的 `universes` 列表不在这里改。选项流改继承 `OptionsFlowWithReload`，删除 `add_update_listener`，重载都交给 HA。
- **理由/代价**：灯具存在 options 里，与地址无关，改地址后重载即可原样恢复。旧地址不补发全 0：换 IP 通常是同一台设备，旧地址上已经没有设备。代价：如果是换成另一台节点，旧节点会保持最后一帧，需要手动关灯或断电。`OptionsFlowWithReload` 只在选项真的变化时才重载，保存相同内容不再重载，这个行为是想要的。

## D-021 集成图标随集成一起发布（`brand/`）
- **日期**：2026-09-19 · **状态**：采纳
- **背景**：集成在 HA 里没有图标。HA 2026.3 起，自定义集成可以在自己目录的 `brand/` 下放 `icon.png` 等文件，不必再向 home-assistant/brands 提交。
- **决定**：提供 `brand/icon.png`（256×256）和 `icon@2x.png`（512×512），图案是 DMX 五芯接口，针脚为 RGBWA 五色，底为靛蓝圆角方块；圆角方块在深色主题里也清楚，所以不单独做 `dark_icon`。没有 logo 时 HA 用 icon 代替。图片由 `tools/make_icon.py`（Pillow，不是项目依赖，在一次性容器里运行）生成。
- **理由/代价**：最低版本已是 2026.9（D-015），所以一定支持。代价：HACS 商店列表的图标仍从 brands 仓库取，所以那里仍没有图标；CI 继续忽略 brands 检查。
