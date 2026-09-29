# Retired Home Assistant release path

2.x and 3.x receive no further releases. Do not run the old sync, publish,
promotion or finalizer workflows to create another old-line app release.
All new FTW releases use the new 0.x packages. This app does not consume
those packages and must not claim to follow every new beta.

The old workflow files and compatibility records remain for audit and
recovery. Their presence does not authorize publication. The
[previous release procedure](https://github.com/srcfl/home-assistant-addons/blob/82172cec84d7d756e35ed40da48e82c59ef5a6f1/RELEASING.md)
describes that historical pipeline; it is not the current release policy.

A future app for the new line needs its own package integration and evidence
on Home Assistant OS/Supervisor before it can be offered. That work has not
shipped. Owners who want current FTW should follow
[the separate-host route](README.md#switch-to-current-ftw) now.
