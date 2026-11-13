**ARES Console** is a net control console for ARES and other emergency nets. It runs on your computer and you use it in your web browser.

## What's new in 1.0.1

- **Start rigctld** and **Start ARDOP** buttons on the Winlink tab, with a status light for each. Set their commands in Settings. On Linux you can choose the radio's sound card for ARDOP with `PULSE_SOURCE=` / `PULSE_SINK=`.
- Starting rigctld checks that the radio actually answers. If it doesn't (wrong serial port, or JS8Call holding the port), you get Hamlib's error message instead of a silent failure.
- Program output is saved to `rigctld.log` and `ardop.log` in the data folder.
- Now MIT licensed. The license file is included in every download.

Upgrading keeps your log and settings.

## Download

| System | File | How to install |
|---|---|---|
| **Windows 10/11** | `ARES-Console-1.0.1-Windows-Setup.exe` | Run it. No admin rights or Python needed. Start it from the Start menu. |
| Windows (no install) | `ARES-Console-1.0.1-Windows-Portable.zip` | Unzip anywhere (even a USB stick) and run `ARES Console.cmd`. |
| **Debian / Ubuntu / Mint / Raspberry Pi OS** | `ares-console_1.0.1_all.deb` | `sudo apt install ./ares-console_1.0.1_all.deb`, then find ARES Console in your menu. |
| Other Linux | `ares-console-1.0.1-linux.tar.gz` | Unpack it, then run `./install.sh` (no root needed), or run `./ares-console` from the folder. Needs Python 3.8+. |

Windows may show a SmartScreen warning because the installer isn't code-signed. Click **More info › Run anyway**. `SHA256SUMS.txt` lists the checksum of every file.

## Features

- **Net log**: quick check-in roster with Present / Away / Checked Out status, location, tactical call and notes. Everything is timestamped in an activity log, and you can set your organization's title.
- **APRS map**: stations you check in are tracked automatically through APRS-IS. You can drop locations such as EOC, shelters and staging areas. **Works offline** with saved USGS map tiles or `.mbtiles` packs.
- **Forms**: ICS-213 (as many as you need), ICS-214, ICS-205 and ICS-309, the NTS Radiogram, the full **Winlink Standard Forms** library, and **SitRepNet MCForms**. Every form is logged.
- **Winlink**: over ARDOP, Telnet to CMS, or Telnet peer-to-peer. You get a list of waiting messages and **choose which to download**. There's also a gateway list, with import from Pat.
- **JS8Call**: send and receive, decode MCForms, band buttons, and a Start JS8Call button.
- **Radio**: Hamlib rigctld VFO readout and tuning, plus an audio **waterfall** on the Winlink and JS8 tabs.
- **Net summary report** when you close the net, which you can print or save as PDF.

## Before relying on it in an event

**Winlink to CMS isn't available yet.** Over the air, the ARDOP link, PTT and Winlink login all work: they were tested through an RMS gateway. But the live Winlink CMS only accepts approved client programs, and ARES Console hasn't been approved yet, so the CMS ends the session after login. Approval is being requested from the Winlink Development Team. Until then, use ARES Console for the net log, map, forms and JS8, and send Winlink mail with an approved client such as Pat or Winlink Express.

Also tested: the Winlink protocol against Pat (send, receive, choosing what to download), live APRS-IS, offline maps, the forms, and the reports. Try a practice session before an event.
