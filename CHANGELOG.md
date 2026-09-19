# Changelog

格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本遵循 [SemVer](https://semver.org/lang/zh-CN/)。版本号以 `custom_components/artnet_light/manifest.json` 为准，与 git tag `vX.Y.Z` 一致。

## [0.1.3] - 2026-09-19

### 修复
- 关灯状态下重启 HA 后，再开灯会回到默认的全亮白色：现在上次的亮度、颜色、色温通过 `ExtraStoredData` 保存，关灯时也不会丢失；0.1.2 及更早保存的状态仍从状态属性恢复

### 测试
- HA 测试新增：关灯重启后开灯恢复原亮度/颜色/色温（RGB、CCT）；旧版状态（只有属性）仍能恢复并重发

## [0.1.2] - 2026-09-19

### 修复
- 适配 HA 2026.x 对 `DeviceInfo(via_device=...)` 的弃用（HA 2027.8 起会失效）：灯具设备改在 `async_setup_entry` 中创建，用 `via_device_id` 挂到节点下，兼容 2024.11 及以后的版本

### 测试
- 在线上 HA 2026.9.2 完成端到端验证：局域网 ArtPoll 发现、添加节点、添加灯具后实体立即出现、颜色/亮度/2 秒渐变/关灯的 DMX 值、重启后恢复状态并重发、设备归属
- HA 测试新增断言：灯具设备挂在节点设备下

## [0.1.1] - 2026-09-19

### 修复
- 数字输入框在没有单位时传入 `unit_of_measurement=None`，HA 会拒绝，导致手动添加节点和添加/修改灯具的表单无法打开
- 发送循环改由 HA 管理（`entry.async_create_background_task`），卸载和关闭 HA 时能被正确取消

### 测试
- HA 配置流/选项流测试首次在 Linux 上跑通：py3.13 + HA 2026.2.3、py3.14 + HA 2026.9.2
- 核心测试和 HA 测试拆成两次 pytest 运行（HA 插件会禁用 socket、替换事件循环）

## [0.1.0] - 2026-09-19

### 新增
- Art-Net 协议层（ArtDmx / ArtPoll / ArtPollReply），无第三方依赖
- 节点自动发现：添加集成时扫描 + 后台每 5 分钟扫描弹出“已发现”卡片；支持手动输入 IP / 广播地址
- 选项流菜单：添加 / 修改 / 删除灯具，发送设置；保存后立即生效
- 灯具类型 Dimmer / CCT（冷暖两路或亮度+色温）/ RGB / RGBW / RGBWW，8/16 位，通道顺序，最小/最大输出，色温范围
- 发送模式：变化即发 + 保活 / 固定帧率连续发送；`transition` 渐变与默认渐变时间
- 重启后恢复灯具状态并重发
- 中英文界面翻译、HACS 支持、CI（hassfest / HACS / pytest）
- `tools/fake_node.py` 模拟节点
