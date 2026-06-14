# Grok Register GUI

一个基于 Tkinter + DrissionPage 的 Grok 注册流程自动化桌面工具。程序提供图形界面，可配置邮箱服务商、代理、注册数量，并在注册成功后保存登录凭据结果。

> 仅用于你有授权的自动化测试、学习和个人环境验证。使用前请确认符合目标服务条款、当地法律法规以及相关邮箱/API 服务的使用规则。

## 功能

- 图形化批量注册流程
- 支持 `duckmail`、`yyds`、`cloudflare` 邮箱服务商
- 支持 HTTP/HTTPS 代理配置
- 可选择注册后自动开启 NSFW 设置
- 自动保存本地配置到 `config.json`
- 注册结果按批次保存为本地 `.txt` 文件
- 支持停止当前批次并保存已完成结果

## 环境要求

- Windows
- Python 3.12 或 3.13
- Chrome / Chromium 浏览器
- 可访问目标站点与所选邮箱服务商 API 的网络环境

脚本内置了对 Python 3.14+ 的兼容性提示，并会尝试切换到本机更稳定的 Python 3.12/3.13 解释器。

## 安装

建议使用虚拟环境：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install DrissionPage curl_cffi
```

如果 PowerShell 禁止激活虚拟环境，可以临时调整执行策略：

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

## 运行

```powershell
python grok_register.py
```

启动后会打开桌面 GUI。在界面中填写邮箱服务商、注册数量、代理和对应 API 配置，然后点击开始注册。

## 配置说明

程序会在项目根目录生成 `config.json`，用于保存 GUI 中填写的配置。该文件包含 API Key、JWT、鉴权密码、代理等本地敏感信息，已经加入 `.gitignore`，不要上传到仓库。

主要配置项：

| 字段 | 说明 |
| --- | --- |
| `email_provider` | 邮箱服务商：`duckmail`、`yyds` 或 `cloudflare` |
| `duckmail_api_key` | DuckMail API Key，可按服务要求填写 |
| `yyds_api_key` | YYDS API Key |
| `yyds_jwt` | YYDS JWT，使用 YYDS 时至少填写 API Key 或 JWT |
| `cfmail_api_base` | Cloudflare Mail API 地址 |
| `cfmail_admin_auth` | Cloudflare Mail 管理端鉴权 |
| `cfmail_custom_auth` | Cloudflare Mail 站点鉴权 |
| `cfmail_domain` | Cloudflare Mail 邮箱域名 |
| `proxy` | 代理地址，例如 `http://127.0.0.1:7890` |
| `enable_nsfw` | 注册成功后是否开启 NSFW |
| `register_count` | 当前批次注册数量 |
| `user_agent` | 浏览器 User-Agent |

## 邮箱服务商

### DuckMail

选择 `duckmail` 后，可填写 DuckMail API Key。程序会通过 DuckMail API 创建邮箱、接收验证码邮件并读取验证码。

### YYDS

选择 `yyds` 后，需要至少填写 `YYDS API Key` 或 `YYDS JWT`。程序会通过 YYDS API 创建邮箱、收取验证码并完成后续流程。

### Cloudflare

选择 `cloudflare` 后，需要填写 `CF Mail API` 和 `CF Admin 密码`。如使用私有域名、站点鉴权或随机二级域名，也需要按界面提示补充相关配置。

## 输出文件

注册成功后，程序会把本批次拿到的 `sso` 登录凭据保存到类似下面格式的文件：

```text
2026.06.14_22.35_1.txt
```

这些结果文件属于敏感数据，已经加入 `.gitignore`，不要上传或分享。

## 可选扩展

如果项目根目录存在 `turnstilePatch` 目录，程序会自动把它作为 Chromium 扩展加载。没有该目录时程序仍会继续运行。

## 常见问题

### 运行时报 DrissionPage 或 curl_cffi 找不到

说明依赖没有安装到当前 Python 环境。先确认虚拟环境已激活，再执行：

```powershell
pip install DrissionPage curl_cffi
```

### 浏览器没有正常启动

确认本机已安装 Chrome / Chromium，并检查代理配置是否可用。如果网络环境不需要代理，可以在 GUI 中清空代理输入框。

### Python 3.14 出现兼容性问题

建议安装并使用 Python 3.12 或 3.13：

```powershell
py -3.12 grok_register.py
```

## Git 忽略项

以下内容不应提交到仓库：

- `.venv/`：本地虚拟环境
- `__pycache__/`：Python 缓存
- `.idea/`：JetBrains IDE 配置
- `__MACOSX/`、`.DS_Store`：系统元数据
- `config.json`、`config.local.json`：本地敏感配置
- `????.??.??_??.??_*.txt`：注册结果文件
