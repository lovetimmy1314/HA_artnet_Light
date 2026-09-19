# Art-Net Light for Home Assistant

通过 Art-Net (DMX over UDP) 控制灯具的 Home Assistant 自定义集成，全部通过 UI 配置。

- 自动发现局域网内的 Art-Net 节点（ArtPoll），也可手动输入 IP / 广播地址
- 一个节点下可挂多个 Universe；灯具在「配置」选项里增、改、删，保存后立即生效，无需重启
- 灯具类型：Dimmer / CCT（冷暖两路 或 亮度+色温）/ RGB / RGBW / RGBWW
- 8 位或 16 位通道、自定义通道顺序、最小/最大输出限制、色温范围
- 支持 `transition` 渐变、默认渐变时间
- 发送模式：变化即发 + 保活，或固定帧率连续发送
- HA 重启后恢复上次状态并重新发送；删除灯具或节点后，不再使用的 Universe 会补发一帧全 0，灯不会一直亮着

## 安装

**HACS**：HACS → 集成 → 右上角菜单 → 自定义存储库，填入本仓库地址，类别选「Integration」，安装后重启 HA。

**手动**：把 `custom_components/artnet_light` 复制到 HA 配置目录的 `custom_components/` 下，重启 HA。

需要 Home Assistant 2026.9 或更新版本（只适配最新版）。

## 使用

### 1. 添加节点
设置 → 设备与服务 → 添加集成 → 搜索 **Art-Net Light**。

- 集成会先扫描 3 秒，列出发现的节点；选择一个即可添加。
- 没有发现节点、或选择「手动输入地址」时，填写 IP（或广播地址如 `192.168.1.255`）、端口（默认 6454）和名称。

添加第一个节点后，集成会在后台每 5 分钟扫描一次，发现新节点时会在「设备与服务」页出现“已发现”卡片。
> 注意：HA 只有在集成已有条目时才会加载它，所以**第一个节点**要通过「添加集成」时的扫描或手动输入来添加。

### 2. 添加灯具
在节点条目上点击 **配置**：

| 菜单 | 说明 |
|---|---|
| ➕ 添加新灯具 | 名称、类型、Universe、起始通道、8/16 位；「高级参数」里可设通道顺序、CCT 模式、色温范围、最小/最大输出 |
| ✏️ 修改/删除已有灯具 | 选中灯具后修改参数，或勾选「删除此灯具」 |
| ⚙️ 发送设置 | 发送模式、保活间隔、帧率、默认渐变时间 |

保存后实体立即出现，例如名称「客厅灯带」→ `light.ke_ting_deng_dai`。
每个灯具会作为一个独立设备，挂在对应的节点下。

### 通道顺序字母

| 字母 | 含义 |
|---|---|
| R G B | 红 绿 蓝 |
| W | 白 / 暖白 |
| C | 冷白 |
| I | 亮度（Dimmer，或 CCT 亮度+色温模式） |
| T | 色温（0 = 最暖，满值 = 最冷） |

各类型默认顺序：Dimmer `I`，CCT `CW` 或 `IT`，RGB `RGB`，RGBW `RGBW`，RGBWW `RGBCW`。
16 位模式下，每个字母占两个连续通道（高字节在前）。

## 开发 / 测试

```bash
# 与 HA 无关的核心逻辑（协议、灯具换算、发送器），任意 Python >= 3.11
pip install pytest
python -m pytest tests/test_core.py -q -p no:homeassistant

# 配置流 / 选项流 / 实体测试，需要 Linux + Python >= 3.12（pytest.ini 只收集 tests/ha）
pip install -r requirements_test.txt
python -m pytest -q tests/ha
```

两组测试必须分两次运行：HA 的 pytest 插件会禁用 socket、替换事件循环，会让核心层的 UDP 测试失败。

`tools/fake_node.py` 是一个模拟 Art-Net 节点：它会应答 ArtPoll，并打印收到的 DMX 数据。在 HA 所在局域网的另一台电脑上运行：

```bash
python tools/fake_node.py --name TestNode --universes 0 1
```

## 许可证

[Apache-2.0](LICENSE)
