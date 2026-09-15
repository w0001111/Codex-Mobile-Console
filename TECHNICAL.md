# 技术与维护说明

[返回使用指南](README.md) · [安装与部署](INSTALL.md) · [发布签名](SIGNING.md)

## 连接方式

```text
消息软件 → cc-connect → 控制台适配器 → Mac 上的 Codex 原任务
手机网页 → 自己的 HTTPS 入口 → 控制台后端 → 同一个 Codex 原任务
```

网页登录后不经过消息软件转发操作。登录采用“消息平台一次性登录码＋独立密码”。首次绑定码用于确认本机拥有者身份，网页登录码用于一次网页登录，两者不能互换。

这套方案适用于 Mac 在家庭或办公室网络内、手机需要通过流量访问的场景：

```
手机 HTTPS 443 → 云服务器 TCP 转发 → SSH 反向隧道 → Mac Caddy 9443 → 本机后端 9840
```

服务器只转发 TLS 字节，证书和解密留在 Mac。需保持公网域名解析正确，服务器 TCP 443 可达，Mac 隧道持续在线。自动证书的 TLS-ALPN 验证要求公网 443 最终到达 Caddy，见 [Caddy HTTPS 说明](https://caddyserver.com/docs/automatic-https#tls-alpn-challenge)。

## cc-connect 版本与适配

安装包固定使用 cc-connect v1.4.1 的上游提交，并附带控制台适配补丁。安装脚本负责下载、校验、打补丁和构建，不依赖原作者电脑上的定制程序。固定提交、源码校验值与补丁校验值见 `patches/cc-connect.json`。

支持的平台取决于本包固定的版本。上游后来增加的平台，需要更新适配并重新验证后才能加入本包。当前平台清单、凭据和权限入口见 [安装指南](INSTALL.md#第二步选择平台并绑定自己)。

## 配置与升级

所有本机状态默认位于 `private/`。`MOBILE_STATE_DIR` 可改变存储位置，但网页、消息入口、管理命令和常驻服务必须使用同一个值。`.env.example` 仅作说明，程序不自动加载 `.env`。

升级前先停止当前安装的常驻服务，并备份自己的 `private/`。不要直接覆盖身份配置，也不要用上游 cc-connect 的自动升级命令替换本包适配版。Codex 桌面内部协议可能随客户端升级变化，应在升级后重新检查历史读取和原任务连接。

## 发布范围与验证边界

本包包含网页及桥接源码、安装和配置向导、固定上游版本/校验值、cc-connect 适配补丁和网络部署脚本。依赖和机器人凭据由安装者自己的环境取得；所有运行状态、下载源码、编译程序、证书和平台密钥都不进入公开压缩包。

当前已验证本机干净目录安装、平台通用路由回归及实际引擎到 Python 入口的绑定/配对调用；这不等于每个平台的真实账号都完成了收发实测，也不等于每位安装者的公网配置已验收。具体测试结果见 `RELEASE_REPORT.json`。

再次分发时只使用以下工具生成的包，不压缩整个运行目录：

```sh
.venv/bin/python scripts/package_release.py --output ../codex-mobile-console-release.zip
```

打包会排除 `private/`、`.build/`、`bin/`、`.venv/`、依赖缓存、Git 历史和本机配置，并进行隐私扫描和逐文件哈希核验。项目作者为 [w0001111](https://github.com/w0001111)，项目源码采用 [MIT](LICENSE) 许可；上游和第三方依赖见 `THIRD_PARTY.md`。作者与来源说明见 [AUTHORS.md](AUTHORS.md)，下载验证与维护者签名流程见 [SIGNING.md](SIGNING.md)。登录页和会话列表底部的“关于本应用”可查看署名、版本和许可。

发布公钥指纹（首次信任请从作者已确认的 GitHub 页面独立核对）：

```text
SHA256:JtidyYqZffrkiseyvDLawmxGJmW2r29NiX6CScEn6Kg
```
