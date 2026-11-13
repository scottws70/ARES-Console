First release of **ARES Console**, a net control console for ARES and other emergency nets. It runs on your computer and you use it in your web browser.

## Download

| System | File | How to install |
|---|---|---|
| **Windows 10/11** | `ARES-Console-1.0.0-Windows-Setup.exe` | Run it. No admin rights or Python needed. Start it from the Start menu. |
| Windows (no install) | `ARES-Console-1.0.0-Windows-Portable.zip` | Unzip anywhere (even a USB stick) and run `ARES Console.cmd`. |
| **Debian / Ubuntu / Mint / Raspberry Pi OS** | `ares-console_1.0.0_all.deb` | `sudo apt install ./ares-console_1.0.0_all.deb`, then find ARES Console in your menu. |
| Other Linux | `ares-console-1.0.0-linux.tar.gz` | Unpack it, then run `./install.sh` (no root needed), or run `./ares-console` from the folder. Needs Python 3.8+. |

Windows may show a SmartScreen warning because the installer isn't code-signed. Click **More info › Run anyway**. `SHA256SUMS.txt` lists the checksum of every file.

## What's in 1.0

- **Net log**: quick check-in roster with Present / Away / Checked Out status, location, tactical call and notes. Everything is timestamped in an activity log, and you can set your organization's title.
- **APRS map**: stations you check in are tracked automatically through APRS-IS. You can drop locations such as EOC, shelters and staging areas. **Works offline** with saved USGS map tiles or `.mbtiles` packs.
- **Forms**: ICS-213 (as many as you need), ICS-214, ICS-205 and ICS-309, the NTS Radiogram, the full **Winlink Standard Forms** library, and **SitRepNet MCForms**. Every form is logged.
- **Winlink**: over ARDOP, Telnet to CMS, or Telnet peer-to-peer. You get a list of waiting messages and **choose which to download**. There's also a gateway list, with import from Pat.
- **JS8Call**: send and receive, decode MCForms, band buttons, and a Start JS8Call button.
- **Radio**: Hamlib rigctld VFO readout and tuning, plus an audio **waterfall** on the Winlink and JS8 tabs.
- **Net summary report** when you close the net, which you can print or save as PDF.

## Before relying on it in an event

Tested here: the Winlink protocol against Pat in both directions (send, receive, choosing what to download), live APRS-IS, offline maps, the forms, and the reports. **Not yet tested on the air:** ARDOP over HF and a live Winlink CMS login. Try a practice session first.
