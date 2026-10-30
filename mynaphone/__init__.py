# Copyright (C) 2026 Salman Ravoof
# SPDX-License-Identifier: GPL-3.0-or-later
"""mynaphone: always-on loopback recorder that archives complete songs."""
import os

# numpy's maths library sets memory aside for every CPU thread as it loads, about 30 MB each (490 MB on a
# 16-thread PC), and the audio arithmetic here never uses those threads. With one, Windows has that much more to
# give other apps, which matters when its memory runs nearly full (68 of 69 GB on October 30, 2026).
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

__version__ = "0.1.0"
