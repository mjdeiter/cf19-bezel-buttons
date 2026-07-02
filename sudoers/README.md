# sudoers notes

This project's daemon runs as root via the init service, so it doesn't
itself need sudo rules. The sudo entries below were added on the
reference system purely for interactive diagnosis/rebuilding and are
**not required** to run the daemon in production -- included here only
for completeness of the story in the main README.

```
youruser ALL=(ALL) NOPASSWD: /usr/bin/insmod, /usr/bin/rmmod, /usr/bin/lsmod, /usr/bin/modprobe, /usr/bin/depmod, /usr/bin/evtest, /usr/bin/dmesg
```

Only add rules for commands you're comfortable running without a
password prompt. Avoid blanket `NOPASSWD: ALL`.
