"""Camera-driven manager for the portrait-to-G-code pipeline."""

from __future__ import annotations

import queue
import re
import subprocess
import sys
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from tkinter import StringVar, Tk, messagebox
from tkinter import ttk

import cv2
from PIL import Image, ImageTk


REPO_ROOT = Path(__file__).resolve().parent
SOURCE_IMAGES_DIR = REPO_ROOT / "source images"
GPT_OUTPUT_DIR = REPO_ROOT / "img2gpt" / "history"
GCODE_OUTPUT_DIR = REPO_ROOT / "gcode outputs"
IMG2GPT_SCRIPT = REPO_ROOT / "img2gpt" / "img2gpt.py"
IMG2GCODE_SCRIPT = REPO_ROOT / "img2gcode" / "img2gcode.py"


def timestamp() -> str:
    return datetime.now().strftime("%H-%M_on_%Y-%m-%d")


def slugify(text: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", text.strip().lower()).strip("_")
    return slug or "person"


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path

    for index in range(2, 1000):
        candidate = path.with_name(f"{path.stem}_{index}{path.suffix}")
        if not candidate.exists():
            return candidate

    raise FileExistsError(f"Could not find an unused path for {path}")


@dataclass
class Job:
    job_id: int
    name: str
    stamp: str
    raw_path: Path
    gpt_path: Path
    gcode_path: Path
    model: str
    quality: str


class JobRow:
    def __init__(self, parent: ttk.Frame, job: Job) -> None:
        self.status = StringVar(value="Queued")
        self.output = StringVar(value="")

        self.frame = ttk.Frame(parent, padding=(0, 4))
        self.frame.columnconfigure(1, weight=1)
        self.frame.columnconfigure(3, weight=1)

        ttk.Label(self.frame, text=job.name, width=18).grid(row=0, column=0, sticky="w")
        ttk.Label(self.frame, textvariable=self.status, width=24).grid(
            row=0, column=1, sticky="we", padx=(8, 8)
        )
        self.progress = ttk.Progressbar(self.frame, maximum=100, length=180)
        self.progress.grid(row=0, column=2, sticky="we", padx=(0, 8))
        ttk.Label(self.frame, textvariable=self.output).grid(row=0, column=3, sticky="w")
        self.frame.pack(fill="x")

    def update(self, status: str, progress: int, output: str = "") -> None:
        self.status.set(status)
        self.progress["value"] = progress
        if output:
            self.output.set(output)


class ManagerApp:
    def __init__(self, root: Tk) -> None:
        self.root = root
        self.root.title("Portrait to G-code")
        self.root.geometry("1120x760")

        self.capture = cv2.VideoCapture(0)
        self.current_frame = None
        self.preview_image = None

        self.jobs: queue.Queue[Job] = queue.Queue()
        self.events: queue.Queue[tuple] = queue.Queue()
        self.job_rows: dict[int, JobRow] = {}
        self.next_job_id = 1
        self.worker = threading.Thread(target=self.worker_loop, daemon=True)
        self.worker.start()

        self.name_var = StringVar()
        self.model_var = StringVar(value="gpt-image-2")
        self.quality_var = StringVar(value="medium")
        self.camera_status = StringVar(value="")

        self.build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.update_camera()
        self.poll_events()

    def build_ui(self) -> None:
        main = ttk.Frame(self.root, padding=12)
        main.pack(fill="both", expand=True)
        main.columnconfigure(0, weight=3)
        main.columnconfigure(1, weight=1)
        main.rowconfigure(0, weight=1)

        left = ttk.Frame(main)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        left.rowconfigure(0, weight=1)
        left.columnconfigure(0, weight=1)

        self.preview = ttk.Label(left, anchor="center")
        self.preview.grid(row=0, column=0, sticky="nsew")
        ttk.Label(left, textvariable=self.camera_status).grid(row=1, column=0, sticky="w")

        controls = ttk.Frame(main)
        controls.grid(row=0, column=1, sticky="nsew")
        controls.columnconfigure(0, weight=1)

        ttk.Label(controls, text="Name").grid(row=0, column=0, sticky="w")
        ttk.Entry(controls, textvariable=self.name_var).grid(
            row=1, column=0, sticky="we", pady=(2, 12)
        )

        ttk.Label(controls, text="Model").grid(row=2, column=0, sticky="w")
        ttk.Combobox(
            controls,
            textvariable=self.model_var,
            values=("gpt-image-2", "gpt-image-1-mini"),
            state="readonly",
        ).grid(row=3, column=0, sticky="we", pady=(2, 12))

        ttk.Label(controls, text="Quality").grid(row=4, column=0, sticky="w")
        ttk.Combobox(
            controls,
            textvariable=self.quality_var,
            values=("medium", "high", "low", "auto"),
            state="readonly",
        ).grid(row=5, column=0, sticky="we", pady=(2, 16))

        ttk.Button(controls, text="Take Photo", command=self.take_photo).grid(
            row=6, column=0, sticky="we"
        )

        jobs_box = ttk.LabelFrame(main, text="Jobs", padding=8)
        jobs_box.grid(row=1, column=0, columnspan=2, sticky="nsew", pady=(12, 0))
        jobs_box.columnconfigure(0, weight=1)

        header = ttk.Frame(jobs_box)
        header.pack(fill="x", pady=(0, 4))
        ttk.Label(header, text="Name", width=18).grid(row=0, column=0, sticky="w")
        ttk.Label(header, text="Status", width=24).grid(row=0, column=1, sticky="w", padx=(8, 8))
        ttk.Label(header, text="Progress", width=24).grid(row=0, column=2, sticky="w")
        ttk.Label(header, text="Output").grid(row=0, column=3, sticky="w")

        self.jobs_frame = ttk.Frame(jobs_box)
        self.jobs_frame.pack(fill="both", expand=True)

    def update_camera(self) -> None:
        ok, frame = self.capture.read() if self.capture.isOpened() else (False, None)
        if ok:
            self.current_frame = frame
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            image = Image.fromarray(rgb)
            image.thumbnail((760, 570), Image.Resampling.LANCZOS)
            self.preview_image = ImageTk.PhotoImage(image)
            self.preview.configure(image=self.preview_image, text="")
            self.camera_status.set("Camera ready")
        else:
            self.preview.configure(text="Camera unavailable")
            self.camera_status.set("Camera unavailable")

        self.root.after(30, self.update_camera)

    def take_photo(self) -> None:
        if self.current_frame is None:
            messagebox.showerror("Camera", "No camera frame is available.")
            return

        name = self.name_var.get().strip()
        if not name:
            messagebox.showerror("Name", "Enter a name before taking a photo.")
            return

        SOURCE_IMAGES_DIR.mkdir(exist_ok=True)
        GPT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        GCODE_OUTPUT_DIR.mkdir(exist_ok=True)

        stamp = timestamp()
        stem = slugify(name)
        raw_path = unique_path(SOURCE_IMAGES_DIR / f"{stem}_raw_{stamp}.png")
        gpt_path = unique_path(GPT_OUTPUT_DIR / f"{stem}_coloring_{stamp}.png")
        gcode_path = unique_path(GCODE_OUTPUT_DIR / f"{stem}_{stamp}.gcode")

        cv2.imwrite(str(raw_path), self.current_frame)

        job = Job(
            job_id=self.next_job_id,
            name=name,
            stamp=stamp,
            raw_path=raw_path,
            gpt_path=gpt_path,
            gcode_path=gcode_path,
            model=self.model_var.get(),
            quality=self.quality_var.get(),
        )
        self.next_job_id += 1

        self.job_rows[job.job_id] = JobRow(self.jobs_frame, job)
        self.job_rows[job.job_id].update("Photo saved", 10, raw_path.name)
        self.jobs.put(job)
        self.name_var.set("")

    def worker_loop(self) -> None:
        while True:
            job = self.jobs.get()
            try:
                self.run_job(job)
            except Exception as exc:
                self.events.put((job.job_id, f"Failed: {exc}", 100, ""))
            finally:
                self.jobs.task_done()

    def run_job(self, job: Job) -> None:
        self.events.put((job.job_id, "Creating coloring image", 30, ""))
        self.run_step(
            [
                sys.executable,
                str(IMG2GPT_SCRIPT),
                "--input",
                str(job.raw_path),
                "--output",
                str(job.gpt_path),
                "--model",
                job.model,
                "--quality",
                job.quality,
            ],
        )

        self.events.put((job.job_id, "Converting to G-code", 75, job.gpt_path.name))
        self.run_step(
            [
                sys.executable,
                str(IMG2GCODE_SCRIPT),
                "--file",
                str(job.gpt_path),
                "--threshold",
                "80",
                "--no-minimize",
                "--gcode-output",
                str(job.gcode_path),
            ],
        )

        self.events.put((job.job_id, "G-code ready", 100, job.gcode_path.name))

    def run_step(self, args: list[str]) -> None:
        result = subprocess.run(
            args,
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return

        details = (result.stderr or result.stdout or "").strip()
        if not details:
            details = f"command failed with exit code {result.returncode}"
        raise RuntimeError(details[-700:])

    def poll_events(self) -> None:
        while True:
            try:
                job_id, status, progress, output = self.events.get_nowait()
            except queue.Empty:
                break
            row = self.job_rows.get(job_id)
            if row:
                row.update(status, progress, output)

        self.root.after(100, self.poll_events)

    def close(self) -> None:
        if self.capture.isOpened():
            self.capture.release()
        self.root.destroy()


def main() -> None:
    root = Tk()
    ManagerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
