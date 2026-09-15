# Codex Mobile Console

**离开电脑，也能用手机查看进度、继续本地 Codex 会话。**

通过手机网页或微信、飞书、Telegram 等消息软件，管理你 Mac 上已有的 Codex 任务。

[下载 v0.2.0-rc.6（预发布版）](https://github.com/w0001111/Codex-Mobile-Console/releases/tag/v0.2.0-rc.6) · [安装说明](INSTALL.md) · [使用说明与截图](USAGE.md)

## 界面展示

会话首页、任务详情和登录记录直接预览如下。点击图片可查看大图。

**截图全部使用虚构演示数据，不包含真实研究内容、账号凭据或服务器地址。**

<p align="center">
  <a href="docs/screenshots/overview.png"><img src="docs/screenshots/overview.png" width="250" align="top" alt="会话首页：示例任务、状态概览和演示额度"></a>
  <a href="docs/screenshots/conversation.png"><img src="docs/screenshots/conversation.png" width="250" align="top" alt="任务详情：虚构待办清单的最终回复和消息输入框"></a>
  <a href="docs/screenshots/logins.png"><img src="docs/screenshots/logins.png" width="250" align="top" alt="登录管理：虚构的示例设备和登录记录"></a>
</p>

从左到右：**会话首页 · 任务详情 · 登录记录**。完整操作步骤及空白登录页截图见 [使用说明](USAGE.md)。

## 从这里开始

| 你现在想做什么 | 看哪份说明 |
| --- | --- |
| 还没安装，准备自己部署 | **[安装说明](INSTALL.md)**：准备环境、安装 cc-connect、绑定账号、配置公网和启动服务 |
| 已经部署好，想知道怎么操作 | **[使用说明（含演示截图）](USAGE.md)**：登录、查看进度、切换会话、发送消息、查看结果和管理登录 |

cc-connect 随本项目安装脚本一起安装在 Mac，无需预先单独安装普通版。具体命令、成功检查、已有安装的处理方法见 [cc-connect 安装](INSTALL.md#一起安装控制台和-cc-connect)。

## 你可以用它做什么

| 想做的事 | 在哪里操作 |
| --- | --- |
| 看哪些任务还在运行、哪些等你处理 | 首页的“运行中”“等你处理”“有新结果” |
| 找到之前的会话 | 按任务名称、网页简称或项目搜索，也可按桌面项目分组筛选 |
| 继续一个已有任务 | 打开会话，点击“连接桌面会话”，连接后发送消息 |
| 快速看最终回复 | 会话页优先展示最新最终回复；时间线、成果与执行记录按需展开 |
| 查看任务生成的文件 | 展开会话中的成果入口，查看或下载已登记的任务产出 |
| 固定常用会话 | 使用“网页置顶”和“设置简称” |
| 为某个会话换模型 | 连接空闲会话后点击模型旁的“切换”，设置下一轮模型与推理强度 |
| 看账号剩余额度 | 首页“账号额度”卡片 |
| 检查是否有人登录 | “登录管理”中查看登录记录，单独退出某次登录 |

## 适用范围

当前适合 Mac 用户个人自部署，每套安装绑定一个拥有者。Mac 需联网、保持唤醒，Codex 桌面客户端需打开。手机公网访问按安装指南准备自己的服务器和域名，或接入已有 HTTPS 服务。

目前管理的是 Codex 会话，暂不支持继续 ChatGPT 原聊天，也不提供多人注册共用。

## 其他文档

- [技术与维护](TECHNICAL.md)：连接原理、配置位置、升级及测试范围。
- [下载验证与发布签名](SIGNING.md)：确认发布包来源。
- [隐私说明](PRIVACY.md)：本地数据与公开发布的边界。
- [作者说明](AUTHORS.md)与[第三方许可](THIRD_PARTY.md)。

项目作者：[w0001111](https://github.com/w0001111)。采用 [MIT 许可证](LICENSE)。本项目是第三方工具，并非 OpenAI 或消息平台官方产品。
