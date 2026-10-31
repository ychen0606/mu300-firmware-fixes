# 安装、检查与回退

这些命令针对 README 中列出的 `u30air` 设备和固件版本，在设备已正常开机、能够使用终端时执行。其他版本应先比对脚本和硬件接口。将本仓库或发布源码包复制到设备后，进入包含本文件的目录。

## 核对设备和文件

```sh
set -e
test "$(/opt/mu300/bin/mu300-device)" = u30air
cat /etc/openwrt_release
uname -r
sha256sum -c SHA256SUMS
sh -n fixes/mu300-led
sh -n fixes/extra-modules
sh -n charge-only/overlay/opt/mu300/bin/mu300-charge-mode
sh -n charge-only/overlay/etc/init.d/mu300-charge-mode
```

核对显示的版本与 README 中的验证环境一致，再继续安装。此目录中的完整脚本覆盖对应的系统脚本；若设备已含其他修改，应先审阅 `.patch` 并合并。

## 保存原脚本

```sh
mu300_fix_backup="$(mktemp -d /root/mu300-fixes-before.XXXXXX)"
cp -p /opt/mu300/bin/mu300-led /opt/mu300/bin/extra-modules "$mu300_fix_backup/"
if [ -f /opt/mu300/bin/mu300-charge-mode ]; then
    cp -p /opt/mu300/bin/mu300-charge-mode "$mu300_fix_backup/mu300-charge-mode"
fi
if [ -f /etc/init.d/mu300-charge-mode ]; then
    cp -p /etc/init.d/mu300-charge-mode "$mu300_fix_backup/mu300-charge-mode.init"
fi
if [ -L /etc/rc.d/S09mu300-charge-mode ]; then
    readlink /etc/rc.d/S09mu300-charge-mode > "$mu300_fix_backup/S09mu300-charge-mode.target"
fi
printf 'Original scripts saved in %s\n' "$mu300_fix_backup"
```

记下命令输出的目录。该目录只备份本次涉及的脚本；完整固件、设备校准数据和个人配置应另行保存。

## 安装电量灯和充电等待修复

```sh
cp -p fixes/mu300-led /opt/mu300/bin/mu300-led
cp -p fixes/extra-modules /opt/mu300/bin/extra-modules
cp -p charge-only/overlay/opt/mu300/bin/mu300-charge-mode /opt/mu300/bin/mu300-charge-mode
cp -p charge-only/overlay/etc/init.d/mu300-charge-mode /etc/init.d/mu300-charge-mode
chmod 755 /opt/mu300/bin/mu300-led /opt/mu300/bin/extra-modules
chmod 755 /opt/mu300/bin/mu300-charge-mode /etc/init.d/mu300-charge-mode
/opt/mu300/bin/mu300-charge-mode check
/etc/init.d/mu300-charge-mode enable
sync
```

`check` 只读检查当前启动模式和硬件条件。充电等待要求现有 `/etc/mu300/power.conf` 中 `POWER_ON_CHARGER` 不为 `1`；原验证系统默认是 `0`。使能服务后，下一次关机插电才会进入充电等待。不要在正在运行的系统上手动执行 `mu300-charge-mode boot`。

进入充电等待后，热点、SSH、ADB 和 Tailscale 均不会启动。长按电源约三秒并松开后，才继续正常启动并恢复管理连接。系统会在 RAM 和 `/root/mu300-charge-mode/` 保存等待和退出记录，正常开机后可用于核对。

## Tailscale 开机自启

已有 Tailscale 安装和登录状态时，执行：

```sh
test -x /etc/init.d/tailscale
/etc/init.d/tailscale enable
sync
/etc/init.d/tailscale enabled
readlink /etc/rc.d/S80tailscale
tailscale status
```

正确启动链接指向 `../init.d/tailscale`。`enable` 保存开机自启；如果当前服务未运行，可执行 `/etc/init.d/tailscale start`。自启表示进程会运行，是否在线还取决于网络和控制服务器连接；用 `tailscale status` 核验。首次安装和登录使用设备自己的账户，不导入其他设备的状态或密钥。

## 回退

只撤销新增充电等待时，在本目录执行：

```sh
sh charge-only/rollback.sh
```

这会移除对应的启动链接，从下一次启动起恢复原启动流程，并保留脚本。电量灯与模块初始化的回退，需将保存目录中的 `mu300-led` 和 `extra-modules` 复制回 `/opt/mu300/bin/`、确认可执行权限并执行 `sync`；后续正常启动使用恢复后的脚本。如果安装前已有其他充电补丁，按保存的脚本和启动链接记录恢复原状态。

## 模拟测试

在装有 Python 3 的主机上运行：

```sh
python3 charge-only/test_charge_mode.py
```

测试使用临时目录、模拟 sysfs 和替代命令，不连接设备或调用主机的真实关机、挂载和模块加载命令。设备 BusyBox ash 的模拟测试命令为：

```sh
sh charge-only/smoke_on_device.sh charge-only/overlay/opt/mu300/bin/mu300-charge-mode
```

模拟测试不能代替真实关机插电、持续充电、长按恢复和拔线关机的硬件验证。
