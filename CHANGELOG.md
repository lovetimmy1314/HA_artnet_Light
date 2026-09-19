# Changelog

格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本遵循 [SemVer](https://semver.org/lang/zh-CN/)。版本号以 `custom_components/artnet_light/manifest.json` 为准，与 git tag `vX.Y.Z` 一致。

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
