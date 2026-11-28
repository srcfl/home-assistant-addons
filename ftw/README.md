# FTW — old release line

This folder is the retired 3.x build context; CI still builds it against a
fixture. It never carries a manifest, and no app may use the slug `ftw` again:
an install may still hold it. The new stable app is `ftw-0x`, in
[`ftw-0x/`](../ftw-0x/DOCS.md).

2.x and 3.x receive no further updates. This app does not follow new 0.x.
No stable version of this app was ever published; its only listed version,
`0.1.0-beta.1`, left the store on 18 September 2026. New installs use
[FTW (beta)](../ftw-0x-beta/DOCS.md) (`ftw-0x-beta`, version 0.x).

Use [Install and update FTW](https://github.com/srcfl/ftw/blob/master/docs/native-beta.md)
to run current FTW on a separate Linux host. Keep a backup of this app and
stop its Core, Start on boot and Watchdog before the new host takes control.
A new setup is available now; guided transfer of old data is not ready.

For an existing installation, see [the app guide](DOCS.md) and the
[compatibility record](../COMPATIBILITY.md).
