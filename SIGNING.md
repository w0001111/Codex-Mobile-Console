# 发布来源验证

项目作者：[w0001111](https://github.com/w0001111)。源码采用 MIT 许可。

当前发布密钥指纹：

```text
SHA256:JtidyYqZffrkiseyvDLawmxGJmW2r29NiX6CScEn6Kg
```

公开密钥文件：`release-signing.pub`。算法：Ed25519；签名格式：OpenSSH SSHSIG；用途命名空间：`codex-mobile-release`。

## 下载者：先核对来源，再安装

1. 从你已确认属于作者的 GitHub 账号页面进入其项目仓库，独立核对上面的指纹。仅下载到同一个压缩包里的公钥不能建立信任，攻击者可能同时替换包、公钥和说明。
2. 从 Release 同时下载 ZIP、对应 `.zip.sig`、`release-signing.pub`。GitHub 自动生成的 Source code ZIP 与作者签名的 ZIP 字节不同，不能混用签名。
3. 使用本机 OpenSSH 验证，成功后才运行安装脚本。公钥文件应只有一行 Ed25519 公钥。以下示例使用当前版本文件名；其他版本替换 ZIP 与签名文件名。

```sh
ssh-keygen -lf release-signing.pub -E sha256
```

确认输出的 SHA256 指纹与独立可信来源完全一致，再执行：

```sh
printf 'release-author namespaces="codex-mobile-release" ' > release.allowed_signers
cat release-signing.pub >> release.allowed_signers
ssh-keygen -Y verify \
  -f release.allowed_signers -I release-author -n codex-mobile-release \
  -s codex-mobile-console-0.2.0-rc.7.zip.sig \
  < codex-mobile-console-0.2.0-rc.7.zip
```

退出码为 0，且显示 `Good ... signature` 才算验证成功。没有验证成功时，不要执行包内程序。
以上命令使用系统工具，验签前不需要运行待验证包里的代码。

已信任本项目工具源码时，也可使用 Python 3.9+ 的辅助命令：

```sh
python3 scripts/release_signature.py verify ../codex-mobile-console-0.2.0-rc.7.zip \
  --signature ../codex-mobile-console-0.2.0-rc.7.zip.sig \
  --public-key release-signing.pub \
  --trusted-fingerprint SHA256:JtidyYqZffrkiseyvDLawmxGJmW2r29NiX6CScEn6Kg
```

指纹参数必须来自你独立确认的来源。辅助工具不会把包内公钥自动视为可信公钥。
SHA256 文件校验表用于检查完整性，本身不构成作者身份认证。

## 维护者：签署发布版本

签名私钥只保存在维护者自己的安全位置，不在源码、发布包或服务器配置中。
发布工具不生成默认密码、不内置私钥、不连接作者服务器，也不改变安装者的登录认证。
自部署用户不需要作者的私钥；Fork 作者应使用自己的署名和独立发布密钥，同时保留原有版权及第三方许可。

生成新密钥时，在源码目录之外执行以下命令，并按提示设置私钥口令：

```sh
umask 077
mkdir -p "$HOME/.local/share/codex-mobile-signing"
ssh-keygen -t ed25519 -a 64 \
  -f "$HOME/.local/share/codex-mobile-signing/release_ed25519" \
  -C 'release-signing'
```

新项目或 Fork 将 `.pub` 文件的前两列复制为源码根目录的 `release-signing.pub`，不保留机器名或本机账号注释。
同步更新 `AUTHOR.json`、`AUTHORS.md`、`LICENSE` 中的项目署名和本文件的公钥指纹；原作者及第三方版权声明仍须保留。
版本号写入 `VERSION`。`AUTHOR.json`、`VERSION` 和 `LICENSE` 会在构建时直接用于“关于”页面。

完成源码检查、测试、前端构建与隐私扫描后，先生成最终 ZIP，再签名：

```sh
python3 scripts/package_release.py --output ../codex-mobile-console-release.zip
python3 scripts/release_signature.py sign ../codex-mobile-console-release.zip \
  --private-key "$HOME/.local/share/codex-mobile-signing/release_ed25519" \
  --public-key release-signing.pub \
  --output ../codex-mobile-console-release.zip.sig
```

工具先核对签名与公开密钥一致，再保存签名；拒绝覆盖已有签名及使用源码树内的私钥。
更改任何发布文件后必须重新构建 ZIP，并用新版本名重新签署。不要把旧签名套用在重新压缩的文件上。

上传 GitHub 时附上 ZIP、`.zip.sig` 和公钥，将公钥指纹同时放在你控制的 GitHub 个人主页或仓库 README。
本项目公开仓库为 [w0001111/Codex-Mobile-Console](https://github.com/w0001111/Codex-Mobile-Console)，已发布版本见 [Releases](https://github.com/w0001111/Codex-Mobile-Console/releases)。文件签名不会自动让 GitHub 提交显示 Verified；提交签名是另一个功能。

## 私钥保管与身份边界

- 目录权限应为 700，私钥为 600。若已有私钥尚无口令，用 `ssh-keygen -p -f <私钥路径>` 在本机交互添加口令；这不会改变公钥及指纹。
- 保留加密离线备份并妥善保管口令。不要把发布私钥当作服务器 SSH 登录密钥，不要加入 `authorized_keys`。
- 私钥遗失或泄露后，通过原 GitHub 账号公开撤销旧指纹、启用新密钥；疑似泄露时不要仅依赖旧密钥签署换钥说明。
- 签名证明对应密钥签署了文件，不单独证明真实姓名、法律版权归属、原创性或软件无漏洞。应另行私下保存原始设计、开发记录和账号归属证据。
- “关于”页面仅展示构建时元数据；它不会自动验证正在运行的服务器，也不会给修改后的部署盖上已验证标记。

协议参考：[OpenSSH ssh-keygen 手册](https://man.openbsd.org/ssh-keygen)。
