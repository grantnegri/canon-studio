# Contributing

Bug reports, camera compatibility results, and focused pull requests are welcome.

For a bug report, include the camera and lens model, distribution, kernel, Python/libgphoto2/FFmpeg versions, steps to reproduce, and the relevant error. Remove personal paths, serial numbers, private images, and audio from shared logs or attachments. Report what you actually tested; support for one Canon model does not establish support for another.

For code changes:

- Keep camera operations serialized through the bridge. A second USB owner can break streaming.
- Preserve loopback-only serving, private runtime files, and captures outside the checkout.
- Keep dependencies small and explain user-visible behavior changes.
- Add focused tests for meaningful behavior changes and run `python3 -m unittest discover -s tests -v`.
- Identify hardware checks performed and anything that remains untested.

Please use synthetic images for UI examples and tests. Do not commit camera captures, credentials, runtime files, or personal machine configuration.

By submitting a contribution, you agree to license it under this project's MIT license.
