# CF-19 Front Bezel Buttons on Linux (Artix/OpenRC, kernel 6.18)

Getting the four extra front-bezel buttons working on a Panasonic
Toughbook CF-19 (brightness already worked out of the box via the
mainline `panasonic_laptop` driver -- this covers the other four:
**Security/lock**, **Rotate**, **Enter**, and **Input Panel**).

Tested on: Artix Linux (OpenRC), kernel `6.18.9-artix1-2`, Openbox WM.
Should generalize to any distro/kernel with minor path adjustments.

## TL;DR

1. Two of the five physical elements on the bezel are handled by the
   in-tree `panasonic_laptop` driver (brightness rocker). The other
   four sit on a *separate* ACPI device (`MAT001F`/`MAT0020`) that
   has **no driver bound to it at all** on stock kernels -- that's
   why they silently do nothing.
2. [Heiher's `panasonic-hbtn` driver](https://github.com/hevz/panasonic-hbtn)
   (2012, GPLv2) targets exactly that ACPI device. It needed two small
   patches to build against a modern (6.x) kernel -- see
   [`driver/panasonic-hbtn.c`](driver/panasonic-hbtn.c) and the diff below.
3. Once loaded, the driver exposes a normal `/dev/input/eventX` device
   generating real key events (`KEY_SCREENLOCK`, `KEY_DIRECTION`,
   `KEY_ENTER`, `KEY_KEYBOARD`) -- but nothing *acts* on them yet.
4. [`daemon/panasonic-hbtn-daemon.py`](daemon/panasonic-hbtn-daemon.py)
   reads that device directly (bypassing any X/Wayland-specific
   keysym mapping headaches) and runs real actions: lock the screen,
   rotate the display, toggle an on-screen keyboard.

## How we diagnosed it

- `cat /proc/bus/input/devices` showed the mainline `panasonic_laptop`
  driver bound and working (explains why brightness worked).
- Listening on that device with `evtest` while pressing the other
  buttons produced **zero events** -- so nothing at the OS level was
  even seeing them.
- Checking `/sys/bus/acpi/devices/` for Panasonic-prefixed (`MAT00xx`)
  ACPI HIDs showed **two additional devices with no driver bound**:
  `MAT001F` and `MAT0021`. That's the smoking gun -- there was no
  missing config, no permissions issue, just literally no driver
  claiming that hardware.
- Heiher's `panasonic-hbtn` project targets those exact ACPI IDs.

## Building the driver

The original 2012 source doesn't compile as-is against a modern
kernel. Two mechanical fixes were needed (both already applied in
[`driver/panasonic-hbtn.c`](driver/panasonic-hbtn.c) in this repo):

```diff
- static int acpi_pcc_hbtn_remove(struct acpi_device *device)
+ static void acpi_pcc_hbtn_remove(struct acpi_device *device)
  {
      struct pcc_acpi *pcc = acpi_driver_data(device);
      if (!device || !pcc)
-         return -EINVAL;
+         return;
      acpi_pcc_destroy_input(pcc);
      kfree(pcc);
-     return 0;
  }
```
(the `.ops.remove` callback in `struct acpi_driver` changed from
returning `int` to `void` around kernel 5.9+)

and removing calls to `sparse_keymap_free()`, which no longer exists
-- keymap teardown is handled automatically now via devres when you
call `sparse_keymap_setup()`.

```bash
cd driver/
make
sudo insmod panasonic-hbtn.ko   # temporary, test before installing
```

Verify it bound correctly:
```bash
readlink -f /sys/bus/acpi/devices/MAT001F:00/driver
# should print: /sys/bus/acpi/drivers/Panasonic Tablet Button Support
```

Verify events actually fire (find the right event number from
`/proc/bus/input/devices`, look for "Panasonic Tablet Button Support"):
```bash
sudo evtest /dev/input/eventN
# press buttons, you should see Event: ... type 1 (EV_KEY) lines
```

### Install permanently

```bash
sudo mkdir -p /lib/modules/$(uname -r)/extra
sudo install -m 0644 panasonic-hbtn.ko /lib/modules/$(uname -r)/extra/
sudo depmod -a
```

**Autoload on boot -- OpenRC:**
```bash
echo 'modules="panasonic-hbtn"' | sudo tee -a /etc/conf.d/modules
```
(the `modules` OpenRC service must be in your `boot` runlevel --
check with `rc-update show`)

**Autoload on boot -- systemd** (untested on the reference system,
but this is the standard mechanism):
```bash
echo panasonic-hbtn | sudo tee /etc/modules-load.d/panasonic-hbtn.conf
```

## The action daemon

The kernel module alone just generates key events -- it doesn't lock
your screen or rotate anything by itself. `daemon/panasonic-hbtn-daemon.py`
reads `/dev/input/eventX` directly (found dynamically by device name,
so the event number doesn't need to be hardcoded) and shells out to:

- **Security button** -> `i3lock` (swap for your locker of choice)
- **Rotate button** -> `xrandr --output <OUTPUT> --rotate <next>`,
  cycling normal -> right -> inverted -> left
- **Input Panel button** -> toggles `onboard` on-screen keyboard
- **Enter** -> no action needed, it's already a real key

Two gotchas this script works around, worth knowing if you adapt it:

1. **Finding `XAUTHORITY`**: the daemon runs as root (no desktop
   session), but the action commands need to run *as* your user
   against *your* X session. There's no reliable static path for
   this across display managers -- the script finds it by scanning
   `/proc/*/environ` for a process that already has both `DISPLAY`
   and `XAUTHORITY` set (e.g. your window manager process).
2. **Detecting current rotation from `xrandr --query`**: don't just
   search the output line for the words "normal"/"right"/etc. --
   `xrandr` always prints a reference list of all four rotation names
   at the end of every connected-output line, so a naive substring
   search always matches. The actual current rotation word (if not
   "normal") appears *between* the resolution/offset and the opening
   `(` of that reference list -- see the regex in `current_rotation()`.
3. **Debounce**: these are old mechanical switches and can generate
   multiple rapid press events from a single physical press. The
   daemon ignores repeat events on the same key within 0.6s.

Edit `TARGET_USER` and `OUTPUT` (get yours from `xrandr --query`) at
the top of the script for your system.

### Running it as a service -- OpenRC

```bash
sudo install -m 0755 daemon/panasonic-hbtn-daemon.py /usr/local/bin/
sudo install -m 0755 service/panasonic-hbtn-daemon.openrc /etc/init.d/panasonic-hbtn-daemon
sudo rc-update add panasonic-hbtn-daemon default
sudo rc-service panasonic-hbtn-daemon start
```

### Running it as a service -- systemd

Not tested on the reference system (OpenRC), but a minimal unit would
look like:
```ini
[Unit]
Description=Handles Panasonic CF-19 front bezel button actions
After=multi-user.target

[Service]
ExecStart=/usr/local/bin/panasonic-hbtn-daemon.py
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

## Identifying your buttons

Per the official Panasonic CF-19 reference manual, the front bezel
has five elements total:

| Element | Icon | Handled by |
|---|---|---|
| Brightness | sun rocker | mainline `panasonic_laptop` driver (works out of the box) |
| Input Panel | keyboard | this project (`KEY_KEYBOARD`) |
| Enter | - | this project (`KEY_ENTER`) |
| Rotation | rotate arrows | this project (`KEY_DIRECTION`) |
| Security | padlock/shield (Ctrl+Alt+Del on Windows) | this project (`KEY_SCREENLOCK`) |

## Credits

- Original driver: [Heiher](https://github.com/heiher), 2012, GPLv2.
  Mirrors also exist at
  [hevz/panasonic-hbtn](https://github.com/hevz/panasonic-hbtn) and
  a few other forks.
- Background pointer to this driver's existence via
  [Bob Johnson's Computer Stuff blog](https://www.bobjohnson.com/blog/adventures-with-linux-xubuntu-on-a-toughbook-cf18/).

## License

The driver (`driver/`) is GPLv2, per the original author. The daemon
and service files in this repo are provided as-is, MIT-style, do
whatever you want with them.
