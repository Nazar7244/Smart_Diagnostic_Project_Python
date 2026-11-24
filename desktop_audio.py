import wave
from pathlib import Path
from tempfile import TemporaryDirectory

from PySide6.QtCore import QElapsedTimer, QFile, QIODevice, QTimer, QUrl, Qt
from PySide6.QtMultimedia import QAudio, QAudioFormat, QAudioOutput, QAudioSource, QMediaDevices, QMediaPlayer
from PySide6.QtWidgets import QFileDialog, QPushButton, QSlider, QWidget

from desktop_visuals import Waveform, column, label, row


class SignalRecorder(QWidget):
    def __init__(self):
        super().__init__()
        self.capture = None
        self.raw_file = None
        self.temp_dir = None
        self.elapsed = QElapsedTimer()
        self.seconds = 0
        self.vibration = False

        self.player = QMediaPlayer(self)
        self.output = QAudioOutput(self)
        self.player.setAudioOutput(self.output)
        self.timer = QTimer(self, interval=80)
        self.timer.timeout.connect(self.tick)

        layout = column(self, (20, 14, 20, 14), 8)
        switch = row(spacing=7)
        self.sound = QPushButton("●  Дыбыс", checkable=True)
        self.vibration_button = QPushButton("≈  Діріл", checkable=True)
        self.sound.clicked.connect(lambda: self.set_vibration(False))
        self.vibration_button.clicked.connect(lambda: self.set_vibration(True))
        switch.addWidget(self.sound)
        switch.addWidget(self.vibration_button)
        layout.addLayout(switch)
        self.waveform = Waveform()
        layout.addWidget(self.waveform)
        controls = row(spacing=11)
        self.record = QPushButton("●")
        self.record.setObjectName("record")
        self.record.setFixedSize(38, 38)
        self.record.clicked.connect(self.toggle_recording)
        controls.addWidget(self.record)
        status = column(spacing=3)
        self.status = label("", "audioStatus")
        self.clock = label("", "micro")
        status.addWidget(self.status)
        status.addWidget(self.clock)
        controls.addLayout(status, 1)
        layout.addLayout(controls)
        self.upload = QPushButton("↑  Аудио файл жүктеу")
        self.upload.setObjectName("outline")
        self.upload.clicked.connect(self.pick_audio)
        layout.addSpacing(4)
        layout.addWidget(self.upload)
        self.preview = QWidget()
        preview = column(self.preview, spacing=4)
        self.filename = label("", "muted", wrap=True)
        self.filename.setTextFormat(Qt.TextFormat.PlainText)
        preview.addWidget(self.filename)
        playback = row(spacing=7)
        self.play = QPushButton("▶")
        self.play.setAccessibleName("Аудионы ойнату")
        self.play.setFixedWidth(32)
        self.play.clicked.connect(self.toggle_playback)
        self.seek = QSlider(Qt.Orientation.Horizontal)
        self.seek.setAccessibleName("Аудио позициясы")
        self.seek.setRange(0, 0)
        self.seek.sliderMoved.connect(self.player.setPosition)
        self.player.durationChanged.connect(lambda duration: self.seek.setRange(0, duration))
        self.player.positionChanged.connect(self.update_position)
        self.player.playbackStateChanged.connect(self.update_play_button)
        self.player.errorOccurred.connect(self.playback_error)
        playback.addWidget(self.play)
        playback.addWidget(self.seek, 1)
        preview.addLayout(playback)
        layout.addWidget(self.preview)
        self.preview.hide()
        self.note = label("", "micro", wrap=True)
        self.note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.note)
        self.set_vibration(False)

    def set_vibration(self, enabled):
        if enabled and self.capture is not None:
            self.stop_recording()
        self.vibration = enabled
        self.sound.setChecked(not enabled)
        self.vibration_button.setChecked(enabled)
        self.note.setText("Нақты діріл өлшеу үшін сыртқы датчик қажет." if enabled else "44.1 kHz · 16-bit · Mono")
        self.update_status()

    def update_status(self):
        recording = self.capture is not None
        self.record.setEnabled(not self.vibration)
        self.record.setText("■" if recording else "●")
        self.record.setAccessibleName("Жазуды тоқтату" if recording else "Жазуды бастау")
        self.status.setText("Жазылып жатыр…" if recording else "Датчик қосылмаған" if self.vibration else "Жазуға дайын")
        source = "External sensor" if self.vibration else "Internal microphone"
        self.clock.setText(f"{self.seconds // 60:02d}:{self.seconds % 60:02d} / {source}")
        self.upload.setEnabled(not recording)
        self.waveform.recording = recording
        self.waveform.update()

    def tick(self):
        self.seconds = self.elapsed.elapsed() // 1000
        source = "Internal microphone"
        self.clock.setText(f"{self.seconds // 60:02d}:{self.seconds % 60:02d} / {source}")
        self.waveform.phase += 0.2
        self.waveform.update()

    def toggle_recording(self):
        if self.capture is not None:
            self.stop_recording()
            return
        device = QMediaDevices.defaultAudioInput()
        if device.isNull():
            self.note.setText("Микрофон табылмады. Аудио файл жүктеуге болады.")
            return

        audio_format = QAudioFormat()
        audio_format.setSampleRate(44100)
        audio_format.setChannelCount(1)
        audio_format.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        if not device.isFormatSupported(audio_format):
            preferred = device.preferredFormat()
            audio_format.setSampleRate(preferred.sampleRate())
            audio_format.setChannelCount(preferred.channelCount())
        if not device.isFormatSupported(audio_format):
            audio_format = device.preferredFormat()
        if audio_format.sampleFormat() not in (QAudioFormat.SampleFormat.UInt8, QAudioFormat.SampleFormat.Int16, QAudioFormat.SampleFormat.Int32):
            self.note.setText("Микрофонның PCM пішімі қолдау таппады. Аудио файл жүктеңіз.")
            return

        try:
            if self.temp_dir is None:
                self.temp_dir = TemporaryDirectory(prefix="smartdiagnost-")
        except OSError:
            self.note.setText("Микрофон жазбасына уақытша қалта ашылмады.")
            return
        self.raw_file = QFile(str(Path(self.temp_dir.name) / "capture.pcm"))
        if not self.raw_file.open(QIODevice.OpenModeFlag.WriteOnly):
            self.raw_file = None
            self.note.setText("Микрофон жазбасына уақытша файл ашылмады.")
            return

        self.player.stop()
        self.capture = QAudioSource(device, audio_format, self)
        self.capture.start(self.raw_file)
        if self.capture.error() != QAudio.Error.NoError:
            self.capture_failed()
            return
        self.capture.stateChanged.connect(self.capture_state_changed, Qt.ConnectionType.QueuedConnection)
        self.seconds = 0
        self.elapsed.start()
        self.timer.start()
        channels = "Mono" if audio_format.channelCount() == 1 else f"{audio_format.channelCount()} арна"
        self.note.setText(f"{audio_format.sampleRate() / 1000:g} kHz · {audio_format.bytesPerSample() * 8}-bit · {channels}")
        self.update_status()

    def capture_state_changed(self, state):
        capture = self.capture
        if capture is not None and self.sender() == capture and state == QAudio.State.StoppedState and capture.error() != QAudio.Error.NoError:
            self.capture_failed()

    def capture_failed(self):
        self.release_capture()
        self.note.setText("Микрофон қолжетімсіз. Рұқсатты тексеріңіз немесе аудио жүктеңіз.")

    def release_capture(self):
        capture, self.capture = self.capture, None
        self.timer.stop()
        if capture is not None:
            capture.stop()
            capture.deleteLater()
            self.raw_file.close()
        self.update_status()

    def stop_recording(self):
        audio_format = self.capture.format()
        raw_path = Path(self.raw_file.fileName())
        self.seconds = self.elapsed.elapsed() // 1000
        self.release_capture()
        self.raw_file = None
        wav_path = raw_path.with_suffix(".wav")
        try:
            if raw_path.stat().st_size < audio_format.bytesPerFrame():
                self.note.setText("Жазба бос. Жазуды қайта бастаңыз.")
                return
            if self.player.source() == QUrl.fromLocalFile(str(wav_path)):
                self.player.setSource(QUrl())
                self.preview.hide()
            with raw_path.open("rb") as source, wave.open(str(wav_path), "wb") as output:
                output.setnchannels(audio_format.channelCount())
                output.setsampwidth(audio_format.bytesPerSample())
                output.setframerate(audio_format.sampleRate())
                while chunk := source.read(4096 * audio_format.bytesPerFrame()):
                    output.writeframesraw(chunk)
            self.load_audio(wav_path, "Микрофон жазбасы")
        except (OSError, wave.Error):
            self.note.setText("Микрофон жазбасын ашу мүмкін болмады.")

    def pick_audio(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Аудио файл жүктеу", "", "Аудио (*.wav *.mp3 *.ogg *.flac *.m4a *.aac *.webm);;Барлық файлдар (*)"
        )
        if path:
            self.load_audio(Path(path), Path(path).name)

    def load_audio(self, path, name):
        self.note.clear()
        self.filename.setText(name)
        self.preview.show()
        self.play.setEnabled(True)
        self.player.setSource(QUrl.fromLocalFile(str(path)))

    def toggle_playback(self):
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def update_play_button(self, state):
        playing = state == QMediaPlayer.PlaybackState.PlayingState
        self.play.setText("Ⅱ" if playing else "▶")
        self.play.setAccessibleName("Аудионы кідірту" if playing else "Аудионы ойнату")

    def update_position(self, position):
        if not self.seek.isSliderDown():
            self.seek.setValue(position)

    def playback_error(self, error, message):
        self.note.setText("Аудио файлды ойнату мүмкін болмады.")
        self.play.setEnabled(False)

    def shutdown(self):
        self.release_capture()
        self.player.setSource(QUrl())
        if self.temp_dir is not None:
            self.temp_dir.cleanup()
