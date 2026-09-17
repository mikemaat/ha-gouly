"""Download and drive a private Android SDK + emulator for key extraction.

Everything lives under one directory (default ~/.gouly-keys) so it never touches an
existing Android Studio install and can be removed with `gouly-keys clean`.
"""

from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.request
import zipfile
from pathlib import Path

from .ui import step, info, warn, download

API_LEVEL = 34
AVD_NAME = "gouly-keys"
EMULATOR_PORT = 5584
SERIAL = f"emulator-{EMULATOR_PORT}"

IS_WINDOWS = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"
HOST_IS_ARM = platform.machine().lower() in ("arm64", "aarch64")
# Emulator image ABI and matching frida-server build.
ABI = "arm64-v8a" if HOST_IS_ARM else "x86_64"
FRIDA_ARCH = "arm64" if HOST_IS_ARM else "x86_64"


class SetupError(RuntimeError):
    """A setup step failed in a way the user needs to fix."""


class AndroidEnv:
    def __init__(self, home: Path) -> None:
        self.home = home
        self.sdk = home / "sdk"
        self.jdk = home / "jdk"
        self.cache = home / "downloads"
        self.avd_home = home / "avd"
        self.user_home = home / "android-user"
        self.emulator_log = home / "emulator.log"
        self._emulator: subprocess.Popen | None = None

    # Paths -----------------------------------------------------------------------------

    @property
    def adb(self) -> Path:
        return self.sdk / "platform-tools" / ("adb.exe" if IS_WINDOWS else "adb")

    @property
    def emulator(self) -> Path:
        return self.sdk / "emulator" / ("emulator.exe" if IS_WINDOWS else "emulator")

    @property
    def sdkmanager(self) -> Path:
        return self.sdk / "cmdline-tools" / "latest" / "bin" / ("sdkmanager.bat" if IS_WINDOWS else "sdkmanager")

    @property
    def system_image(self) -> Path:
        return self.sdk / "system-images" / f"android-{API_LEVEL}" / "google_apis" / ABI

    def env(self) -> dict[str, str]:
        env = dict(os.environ)
        env.update(
            JAVA_HOME=str(self.jdk),
            ANDROID_HOME=str(self.sdk),
            ANDROID_SDK_ROOT=str(self.sdk),
            ANDROID_AVD_HOME=str(self.avd_home),
            ANDROID_USER_HOME=str(self.user_home),
        )
        return env

    # Installation ----------------------------------------------------------------------

    def install(self) -> None:
        for d in (self.sdk, self.cache, self.avd_home, self.user_home):
            d.mkdir(parents=True, exist_ok=True)
        self._install_jdk()
        self._install_cmdline_tools()
        self._install_sdk_packages()
        self._create_avd()

    def _install_jdk(self) -> None:
        java = self.jdk / "bin" / ("java.exe" if IS_WINDOWS else "java")
        if java.exists():
            return
        step("Downloading Java 17 (needed by the Android SDK tools)")
        os_name = "windows" if IS_WINDOWS else "mac" if IS_MAC else "linux"
        arch = "aarch64" if HOST_IS_ARM else "x64"
        url = f"https://api.adoptium.net/v3/binary/latest/17/ga/{os_name}/{arch}/jdk/hotspot/normal/eclipse"
        archive = self.cache / ("jdk17.zip" if IS_WINDOWS else "jdk17.tar.gz")
        download(url, archive)
        staging = self.home / "jdk-staging"
        shutil.rmtree(staging, ignore_errors=True)
        _extract(archive, staging)
        java_bin = next(
            p for p in staging.rglob("java.exe" if IS_WINDOWS else "java") if p.is_file() and p.parent.name == "bin"
        )
        jdk_root = java_bin.parent.parent  # .../bin/java -> JDK root (Contents/Home on macOS)
        shutil.rmtree(self.jdk, ignore_errors=True)
        shutil.move(str(jdk_root), str(self.jdk))
        shutil.rmtree(staging, ignore_errors=True)
        if not IS_WINDOWS:
            for tool in (self.jdk / "bin").iterdir():
                tool.chmod(0o755)

    def _install_cmdline_tools(self) -> None:
        if self.sdkmanager.exists():
            return
        step("Downloading Android command-line tools")
        repo = urllib.request.urlopen("https://dl.google.com/android/repository/repository2-3.xml", timeout=60)
        os_tag = "win" if IS_WINDOWS else "mac" if IS_MAC else "linux"
        names = re.findall(rf"commandlinetools-{os_tag}-(\d+)_latest\.zip", repo.read().decode())
        if not names:
            raise SetupError("Couldn't find the Android command-line tools download.")
        filename = f"commandlinetools-{os_tag}-{max(names, key=int)}_latest.zip"
        archive = self.cache / filename
        download(f"https://dl.google.com/android/repository/{filename}", archive)
        staging = self.home / "cmdline-staging"
        shutil.rmtree(staging, ignore_errors=True)
        _extract(archive, staging)
        target = self.sdk / "cmdline-tools" / "latest"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.rmtree(target, ignore_errors=True)
        shutil.move(str(staging / "cmdline-tools"), str(target))
        shutil.rmtree(staging, ignore_errors=True)
        if not IS_WINDOWS:
            for tool in (target / "bin").iterdir():
                tool.chmod(0o755)

    def _sdk_packages_installed(self) -> bool:
        return self.adb.exists() and self.emulator.exists() and (self.system_image / "system.img").exists()

    def _install_sdk_packages(self) -> None:
        packages = ["platform-tools", "emulator", f"system-images;android-{API_LEVEL};google_apis;{ABI}"]
        if self._sdk_packages_installed():
            return
        step("Downloading the Android emulator and system image (about 2 GB, one time only)")
        subprocess.run(
            [str(self.sdkmanager), f"--sdk_root={self.sdk}", "--licenses"],
            input="y\n" * 50, text=True, env=self.env(), capture_output=True,
        )
        # Package names contain ';', which Windows batch files split on, so pass them via a file.
        package_file = self.cache / "packages.txt"
        package_file.write_text("\n".join(packages) + "\n")
        result = subprocess.run(
            [str(self.sdkmanager), f"--sdk_root={self.sdk}", f"--package_file={package_file}"],
            input="y\n" * 50, text=True, env=self.env(),
        )
        # Newer command-line tools forward sdkmanager to the "Android CLI", which can crash on exit
        # (e.g. 0xC0000409 on Windows) after installing everything, so check the files, not the exit code.
        if not self._sdk_packages_installed():
            raise SetupError(
                f"Installing the Android SDK packages failed (exit code {result.returncode}, see the output above)."
            )

    def _create_avd(self) -> None:
        avd_dir = self.avd_home / f"{AVD_NAME}.avd"
        if (avd_dir / "config.ini").exists():
            return
        info("Creating the emulator")
        avd_dir.mkdir(parents=True, exist_ok=True)
        (self.avd_home / f"{AVD_NAME}.ini").write_text(
            f"avd.ini.encoding=UTF-8\npath={avd_dir}\npath.rel=avd/{AVD_NAME}.avd\ntarget=android-{API_LEVEL}\n"
        )
        sysdir = os.path.join("system-images", f"android-{API_LEVEL}", "google_apis", ABI) + os.sep
        (avd_dir / "config.ini").write_text(
            "\n".join(
                [
                    "avd.ini.encoding=UTF-8",
                    f"AvdId={AVD_NAME}",
                    "avd.ini.displayname=Gouly Keys",
                    f"abi.type={ABI}",
                    f"hw.cpu.arch={'arm64' if HOST_IS_ARM else 'x86_64'}",
                    "hw.cpu.ncore=4",
                    "hw.ramSize=4096",
                    "disk.dataPartition.size=6G",
                    f"image.sysdir.1={sysdir}",
                    "tag.id=google_apis",
                    "tag.display=Google APIs",
                    f"target=android-{API_LEVEL}",
                    "hw.lcd.width=1080",
                    "hw.lcd.height=2340",
                    "hw.lcd.density=440",
                    "hw.keyboard=yes",
                    "hw.gpu.enabled=yes",
                    "hw.gpu.mode=auto",
                    "hw.audioInput=no",
                    "showDeviceFrame=no",
                    "",
                ]
            )
        )

    # Emulator --------------------------------------------------------------------------

    def check_acceleration(self) -> None:
        result = subprocess.run(
            [str(self.emulator), "-accel-check"], env=self.env(), capture_output=True, text=True
        )
        if result.returncode == 0:
            return
        output = (result.stdout + result.stderr).strip()
        hint = (
            "Turn on 'Windows Hypervisor Platform' in 'Turn Windows features on or off', then reboot."
            if IS_WINDOWS
            else "Make sure KVM is available: /dev/kvm must exist and be accessible by your user "
            "(e.g. `sudo usermod -aG kvm $USER`, then log out and back in)."
            if not IS_MAC
            else "Hardware acceleration should work out of the box on macOS; try rebooting."
        )
        raise SetupError(f"The Android emulator can't use hardware acceleration.\n{output}\n\n{hint}")

    def adb_cmd(self, *args: str, timeout: float = 120, check: bool = True) -> str:
        result = subprocess.run(
            [str(self.adb), "-s", SERIAL, *args],
            env=self.env(), capture_output=True, text=True, timeout=timeout,
        )
        if check and result.returncode != 0:
            raise SetupError(f"adb {' '.join(args)} failed: {(result.stderr or result.stdout).strip()}")
        return result.stdout.strip()

    def is_running(self) -> bool:
        result = subprocess.run(
            [str(self.adb), "devices"], env=self.env(), capture_output=True, text=True, timeout=30
        )
        return any(line.startswith(SERIAL) and line.endswith("device") for line in result.stdout.splitlines())

    def start_emulator(self) -> None:
        if self.is_running():
            info("Emulator already running")
        else:
            step("Starting the emulator (a window will open)")
            log = open(self.emulator_log, "w")
            self._emulator = subprocess.Popen(
                [
                    str(self.emulator), "-avd", AVD_NAME, "-port", str(EMULATOR_PORT),
                    "-no-snapshot", "-no-boot-anim", "-no-audio",
                ],
                env=self.env(), stdout=log, stderr=subprocess.STDOUT,
            )
        self._wait_for_boot()
        self._become_root()

    def _wait_for_boot(self, timeout: float = 420) -> None:
        info("Waiting for Android to boot (the first boot can take a few minutes)")
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._emulator is not None and self._emulator.poll() is not None:
                raise SetupError(f"The emulator exited unexpectedly. See {self.emulator_log}")
            try:
                if self.adb_cmd("shell", "getprop", "sys.boot_completed", timeout=15, check=False) == "1":
                    return
            except subprocess.TimeoutExpired:
                pass
            time.sleep(3)
        raise SetupError(f"The emulator didn't finish booting. See {self.emulator_log}")

    def _become_root(self) -> None:
        if self.adb_cmd("shell", "id", "-u", check=False) == "0":
            return
        self.adb_cmd("root", check=False)
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            time.sleep(2)
            try:
                if self.adb_cmd("shell", "id", "-u", timeout=15, check=False) == "0":
                    return
            except subprocess.TimeoutExpired:
                pass
        raise SetupError("Couldn't get root access in the emulator.")

    def stop_emulator(self) -> None:
        subprocess.run(
            [str(self.adb), "-s", SERIAL, "emu", "kill"], env=self.env(), capture_output=True, timeout=30
        )
        if self._emulator is not None:
            try:
                self._emulator.wait(timeout=30)
            except subprocess.TimeoutExpired:
                self._emulator.kill()

    # Apps ------------------------------------------------------------------------------

    def installed_version(self, package: str) -> str | None:
        output = self.adb_cmd("shell", "dumpsys", "package", package, check=False)
        match = re.search(r"versionName=(\S+)", output)
        return match.group(1) if match else None

    def install_apks(self, apks: list[Path]) -> None:
        step("Installing the Gouly app in the emulator")
        self.adb_cmd("install-multiple", "-r", "-g", *[str(p) for p in apks], timeout=600)


def _extract(archive: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    if archive.suffix == ".zip":
        with zipfile.ZipFile(archive) as zf:
            for member in zf.infolist():
                extracted = Path(zf.extract(member, dest))
                mode = member.external_attr >> 16
                if mode and not IS_WINDOWS:
                    extracted.chmod(mode)
    else:
        with tarfile.open(archive) as tf:
            if hasattr(tarfile, "tar_filter"):
                tf.extractall(dest, filter="tar")
            else:
                tf.extractall(dest)
