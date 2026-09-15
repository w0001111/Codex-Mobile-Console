# 安装与部署

[返回首页](README.md) · [已安装？查看使用说明](USAGE.md)

第一次安装时按本页顺序操作。命令默认在 Mac 的安装目录运行；需要在云服务器执行的步骤会单独标明。预计操作路线：安装 → 绑定消息软件 → 设置密码 → 配置公网访问 → 手机登录 → 设置常驻。

## 安装前准备

- 一台运行并登录 Codex 桌面客户端的 Mac，以及匹配的 Codex CLI。桌面内部协议可能随客户端升级变化。
- Python 3.11+、Node.js 20+、npm、Git、Go 1.25+。下载依赖时需要连通 GitHub、PyPI、npm 和 Go 模块服务。
- macOS Command Line Tools（Git / C 编译工具）；未安装时先运行 `xcode-select --install` 并按系统提示完成。
- 自己选择的消息平台机器人及凭据；普通平台账号不一定自动具有机器人权限。
- 手机流量访问：自己的 Ubuntu/Debian 服务器、可用的 SSH 密钥登录，以及指向该服务器的域名。本说明使用域名自动证书；已有合规可用的 IP 证书或自己的 HTTPS 代理时，也可自行接入后端。
- 本机安装 Caddy，参见 [官方安装说明](https://caddyserver.com/docs/install#homebrew-macos)。

已有 Homebrew 时，可以安装缺少的依赖：

```sh
brew install python@3.11 node go caddy
```

本包不会复制原开发者的地址、密码、会话、证书、SSH 密钥或登录状态，也不会自动修改已有 cc-connect、云服务器或 LaunchAgent。

## 第一步：解压并安装

### cc-connect 要装在哪里

**安装到 Mac，随本应用一起安装。** cc-connect 负责收发消息平台的消息；你无需先从其他渠道安装它。本包附带 cc-connect 安装脚本，首次安装会联网生成可执行程序，不是解压后就自带可运行的二进制文件。

在 Mac 解压本项目到一个新的、自己拥有写权限的目录，在终端进入这个目录。不要覆盖正在运行的旧安装。

### 一起安装控制台和 cc-connect

确认已完成上面的“安装前准备”，运行：

```sh
PYTHON_BIN=python3.11 sh scripts/setup.sh
```

等待命令正常结束。它会自动完成以下操作：

1. 安装本项目的 Python 依赖。
2. 安装并构建手机网页。
3. 下载固定版本的 cc-connect，核对源码与适配补丁。
4. 完成适配检查，生成本项目自己的 `bin/cc-connect`。

看到包含 `cc-connect adapter built at bin/cc-connect` 的提示后，执行：

```sh
./bin/cc-connect --version
```

**输出应包含 `v1.4.1-console-multichannel.1`。** 使用带 `./bin/` 的完整命令；直接输入 `cc-connect` 可能运行到电脑里以前安装的版本。

安装完成后继续第二步。需要先选择消息平台、生成配置，再用 `sh scripts/start-channel.sh` 启动机器人连接；安装命令本身不会代替账号绑定。

### 已经装过 cc-connect 怎么办

仍在新的项目目录中执行上面的安装命令。本项目把程序放在本目录的 `bin/cc-connect`，配置由后续向导生成到 `private/cc-connect.toml`，不会覆盖全局 cc-connect 或它已有的配置。

普通上游版本不能直接代替本项目适配版；不要用上游自动升级命令覆盖这里的程序。已有机器人的凭据可以由你在配置向导中重新填写，不要直接覆盖生成的整个配置文件。若要复用同一个机器人，先停止旧实例中该机器人的连接，避免两个实例同时处理同一入口；其他机器人不需要随之停用。

### cc-connect 没有装好怎么办

| 看到的提示或现象 | 接下来怎么做 |
| --- | --- |
| 找不到 Python、Go、Git 或 npm | 回到“安装前准备”安装缺少的工具，再运行完整安装命令 |
| 下载失败、连接超时 | 检查 Mac 能否访问 GitHub 和依赖下载服务，并核对本机代理；恢复网络后重试 |
| `./bin/cc-connect` 不存在 | 前面的安装或构建没有完成，先查看终端报错，不要直接进入绑定步骤 |
| 版本不是预期的适配版 | 确认当前位于本项目目录，使用 `./bin/cc-connect --version`；必要时重新运行完整安装命令 |
| 提示源码或补丁校验不一致 | 不要跳过校验；重新取得正确的发布包或报错中指定的源码归档 |
| 网页依赖已装好，只有 cc-connect 构建失败 | 解决终端提示的问题后，可用下方命令仅重试 cc-connect 的构建 |

已存在本项目 `.venv`、前置依赖安装完成时，可单独重试：

```sh
.venv/bin/python scripts/build_cc_connect.py
./bin/cc-connect --version
```

如无法自动下载上游归档，可以自行下载 `patches/cc-connect.json` 中 `archive_url` 指定的文件，再指定你实际保存的路径：

```sh
.venv/bin/python scripts/build_cc_connect.py --archive /path/to/downloaded-archive.tar.gz
```

把 `/path/to/downloaded-archive.tar.gz` 换成自己的实际文件路径；不能用其他版本的归档代替。这个办法只替代 cc-connect 源码下载，依赖尚未缓存时仍需要联网。

高级路径设置：`GO_BIN` 可指定 Go 程序；`CONTROL_CODEX_BINARY` 可指定不在 PATH 中的 Codex CLI。

## 第二步：选择平台并绑定自己

支持配置该版本注册的全部 16 个平台标识：

`weixin`、`feishu`、`lark`、`telegram`、`discord`、`slack`、`dingtalk`、`wecom`、`qq`、`qqbot`、`line`、`weibo`、`max`、`matrix`、`webex`、`wps-xiezuo`。

同一套菜单、绑定、网页登录及原任务路由适用于这些平台；每次安装选择一个平台和一个拥有者。平台是否允许创建机器人、账号资格、地区可用性、收费和所需权限由相应平台决定。平台后续新增的适配器，需要维护者更新固定版本并重新验证后发布，不代表当前包已经包含未来版本。


```sh
.venv/bin/python scripts/configure.py
```

向导依次询问平台、项目名称、自己的用户 ID、HTTPS 地址和平台选项。密码和平台凭据不通过命令行参数传递。

- **微信**：用户 ID 可以留空，向导会调用扫码流程获取你的身份；平台 options 也可留空。若你已填用户 ID 但未填 token，则按向导提示运行 `sh scripts/weixin-login.sh` 完成扫码。
- **飞书 / Lark**：通常需要 `app_id`、`app_secret`，在平台后台启用机器人和消息接收权限。
- **Telegram / Discord**：通常需要 `token`；Discord 还需按上游说明启用必要的消息权限。
- **Slack**：通常需要 `bot_token`、`app_token` 并配置 Socket Mode。
- **钉钉**：通常需要 `client_id`、`client_secret`。
- 其余平台和完整权限清单：查看安装时保存的 `.build/upstream-reference/config.example.toml` 与 `README.zh-CN.md`，或者 [固定版本的配置示例](https://github.com/chenhg5/cc-connect/blob/5d4c96dd12774574369e75b60084140101c9a59a/config.example.toml)。

平台 options 可输入 JSON 对象（隐藏输入），也可以输入 `@` 加自己私有 TOML 文件的路径。该 TOML 只放平台选项键值，不是整个 cc-connect 配置文件。例如 Telegram 私有文件的内容为 `token = "自己取得的令牌"`。凭据由你在对应平台创建机器人后取得，不在本仓库预设。

向导强制把 `allow_from`、`admin_from` 限制为你指定的单个用户，生成配置到 `private/cc-connect.toml`。不要求手填平台会话 ID。

在另一个终端进入同一安装目录，运行：

```sh
sh scripts/start-channel.sh
```

然后在**自己与机器人之间的私聊**里发送向导显示的 `绑定控制台 …`。绑定同时校验平台、项目、用户和随机码，并记录该私聊的真实会话身份。只在你愿意显示任务内容的私聊中绑定，不能在公共群组绑定。

绑定码 10 分钟有效。过期时在本机重新生成：

```sh
.venv/bin/python scripts/configure.py renew-binding
```

若初次微信扫码中断，也可用此命令恢复尚未完成的绑定流程。

收到“控制台身份已绑定”后，回 Mac 设置独立网页密码：

```sh
.venv/bin/python mobile-ui/local_admin.py set-password
```

密码要求 9–128 字符，不要复用服务器或平台密码。首次绑定不等于已经设置网页密码。

## 第三步：配置自己的公网连接

完成这一节后，手机才能通过流量打开你的控制台。请准备自己的域名和服务器，按顺序完成以下操作。网络结构和端口用途见 [技术说明](TECHNICAL.md)。

1. 在自己的 DNS 管理页把域名 A 记录指向自己的服务器。如果没有正确配置 IPv6，不要发布错误的 AAAA 记录。本文的 `console.example.test` 仅为示例，不能拿它申请实际证书。
2. 在自己的 SSH 配置中建立服务器别名，例如 `console-relay`，使用自己的服务器用户名和密钥。首次手工 `ssh console-relay` 验证主机指纹并确认能登录，再确认 `ssh -o BatchMode=yes console-relay true` 可以免交互完成。不要关闭主机指纹校验。
3. 把本包的 `deploy/install-relay.example.sh` 复制到**自己的新服务器**，检查后在服务器上运行 `sudo sh install-relay.example.sh`。它安装 socat 和一个 TCP 转发服务；若 443 已被占用或同名服务已存在，会拒绝覆盖。已有 HAProxy 等代理的服务器请配置等效 TCP 转发，不运行覆盖安装。
4. 在云防火墙及主机防火墙允许 TCP 443。SSH 使用自己选定的端口。服务器的 19443 是仅供 SSH 反向隧道使用的回环监听，不对公网开放。SSH 服务需要允许该用户进行远程 TCP 转发。
5. 回到 Mac 的安装目录运行：

```sh
.venv/bin/python scripts/configure_network.py
```

向导生成私有 `private/network/Caddyfile` 和 `relay.sh`。LINE 和企业微信回调模式会按平台配置自动加入回调路径转发；将向导给出的回调 HTTPS 地址登记到相应平台后台，并完成平台要求的签名配置。企业微信 websocket 模式不需要该回调路径。若平台首次绑定依赖回调，可先完成此网络步骤，再回到第二步发送绑定码。

分别在终端运行这三个进程（平台入口仍在运行）：

```sh
sh scripts/start-local.sh
```

```sh
sh private/network/relay.sh
```

```sh
XDG_DATA_HOME="$PWD/private/caddy-data" XDG_CONFIG_HOME="$PWD/private/caddy-config" caddy run --config private/network/Caddyfile --adapter caddyfile
```

Caddy 配置模板使用自己的域名；IP 地址的证书需要另行配置。已有 HTTPS 代理时，可直接代理至 `127.0.0.1:9840`，并保持请求 Host 与第二步填写的 HTTPS 来源一致。

不要把桌面 IPC、cc-connect 管理 API、私有状态目录直接暴露到公网。

## 第四步：手机登录与验收

在已绑定的消息软件中发送“界面”，打开自己的 HTTPS 地址，输入新的网页登录码和独立密码。

验证这些行为：

- 用手机流量打开页面，证书被正常信任；未登录时不能读取任务、历史、文件、额度。
- 打开自己一个已存在的测试任务，确认名称、历史和桌面任务 ID 一致；新消息确实出现在同一原任务中。
- 菜单 → 对话 → 切换编号 → 输入文字 → 结果，能看到完整结果；网页任务选择与消息平台当前选择各自独立。
- 退出后不能继续访问；一次性码不能重复使用；其他用户或其他未绑定会话不能进入任务路由。
- Mac 断网重连、服务器重启及证书续期正常。不要向正在进行的科研任务发送测试指令。

可以先运行只读检查器，它不会向 Codex 发消息，也不打印凭据：

```sh
.venv/bin/python scripts/doctor.py --public
```

消息软件里的常用文字：`菜单`、`对话`、`对话 关键词`、`切换 9`、`进度`、`结果`、`界面`、`退出`。未选择桌面任务时，普通文字保留 cc-connect 的默认助手行为；模板默认助手采用只读建议模式，桌面原任务则继承该任务自己的权限。任务运行中或等待确认时不会自动抢占、重发或审批。

## 第五步：设置常驻

手动验证成功后，先结束前面终端里启动的四个进程，再在安装目录运行：

```sh
.venv/bin/python scripts/install_services.py install
```

工具为这个安装目录生成唯一服务名称，启动网页、消息入口、Caddy 和 SSH 隧道，在当前 Mac 用户登录后运行；不会覆盖其他安装或原有服务。Mac 仍需联网、保持唤醒，Codex 桌面客户端需打开。

卸载这些常驻服务：

```sh
.venv/bin/python scripts/install_services.py remove
```

它保留代码和私有数据。更新代码前先停止本安装的服务，保留自己的 `private/`；不要把源码更新当作覆盖身份配置。

## 故障排查

| 现象 | 首先检查 |
| --- | --- |
| 构建下载失败 | 网络、代理、Git/Go 版本；不跳过源码或补丁校验 |
| 平台收不到消息 | 自己的平台凭据、消息权限、连接方式；回调平台还需公网回调验证 |
| 提示未绑定 | 绑定码是否过期；是否在绑定时的同一个私聊、项目和平台 |
| “界面”变成普通 AI 回复 | 是否运行包内适配版、是否加载生成的 `console-router` 命令 |
| 码或密码不正确 | 是否设置独立网页密码、码是否过期或已使用；不要用服务器密码代替 |
| 网页 502 / 无法连接 | 云转发、SSH 隧道、Mac Caddy、网页服务分别是否存活 |
| 登录后任务不可操作 | Codex 桌面是否打开、原任务是否空闲、客户端协议版本是否兼容 |
| 结果分段发送失败 | 在网页查看完整结果，不反复重发原任务指令 |

`MOBILE_STATE_DIR` 可改变私有状态位置，但网页、消息入口、管理命令和常驻服务必须使用同一个值；上文命令示例采用默认 `private/`。`.env.example` 仅为说明，程序不自动加载 `.env`。

忘记独立密码：在本机再次运行 `local_admin.py set-password`，旧网页登录和配对码会撤销。全部退出用 `local_admin.py revoke`。更换消息平台时解压到新目录，重新选择平台并绑定；Codex 原任务保留在桌面客户端，不随控制台副本删除。旧控制台不再使用时移除其常驻服务，并在平台后台撤销旧机器人凭据。


## 忘记网页密码

在 Mac 终端进入本安装目录，运行：

```sh
.venv/bin/python mobile-ui/local_admin.py set-password
```

按提示输入两次新密码，长度为 9–128 个字符。成功后旧网页登录和未使用的登录码失效；回到消息软件发送 `界面` 获取新码，再按 [使用说明](USAGE.md#1-登录手机网页)登录。
