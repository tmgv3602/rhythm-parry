# rhythm_parry.py
# 1ボタン音ゲー: 作曲済みの旋律を「タイミングを当てて演奏する」パリィゲー。
# ファミコン2A03構成 — パルス=リード(プレイヤー) / 三角波=ベース / ノイズ=ドラム。
# ミスするとその音が鳴らない = 旋律に穴が空く = 自分が演奏している実感。
#
# 操作: SPACE / Z / X = パリィ   ← → = 判定窓調整   R = リトライ
# 実行: pip install pyxel && python rhythm_parry.py

import pyxel
import math
import random

W, H = 128, 128

# ---- 位置・判定 ----
PARRY_POINT   = 92
SPAWN_X       = 28
ACTIVE_FRAMES = 7     # 判定窓(±これフレーム以内でパリィ成立)
PERFECT_LATE  = 2     # ±これフレーム以内でPERFECT
COOLDOWN      = 8
MAX_HP        = 3

# ---- タイムアタック ----
TIME_LIMIT_SEC = 30
TIME_LIMIT     = TIME_LIMIT_SEC * 60

# ---- リズム(BPM同期) ----
BPM             = 100
STEPS_PER_BEAT  = 2
FRAMES_PER_STEP = round(3600 / BPM / STEPS_PER_BEAT)
LOOKAHEAD_STEPS = 4
LOOKAHEAD_FR    = LOOKAHEAD_STEPS * FRAMES_PER_STEP
SLASH_SPEED     = (PARRY_POINT - SPAWN_X) / LOOKAHEAD_FR

# 譜面 = 旋律そのもの。各8分ステップに音名("." は休符=斬撃なし)。
# 4小節(32ステップ)。A(問い)→ 受け → B(変化)→ 着地 で反復感を減らす。
MELODY = [
    # bar1  C
    "c3", ".",  "e3", ".",  "g3", ".",  "a3", "g3",
    # bar2  Am
    "e3", ".",  "c3", ".",  "e3", ".",  "g3", ".",
    # bar3  F
    "f3", ".",  "a3", ".",  "c4", ".",  "a3", "g3",
    # bar4  G → 着地
    "g3", ".",  "d3", ".",  "g3", ".",  "e3", "c3",
]

# ベース(拍ごと = 16拍 = 4小節)。C - Am - F - G 進行。
BASS = ["c1", "c1", "c1", "c1", "a1", "a1", "a1", "a1",
        "f1", "f1", "f1", "f1", "g1", "g1", "g1", "g1"]

# 単音を「コードの高速アルペジオ」に変換 — ファミコン式の擬似和音。
# 旋律音を最初に置くので輪郭は保たれ、上に和音のきらめきが乗る。
ARP = {
    "c3": "c3e3g3",
    "d3": "d3f3a3",
    "e3": "e3g3c4",
    "f3": "f3a3c4",
    "g3": "g3c4e4",
    "a3": "a3c4e4",
    "c4": "c4e4g4",
}


class Spark:
    def __init__(self, x, y, fast=False):
        ang = random.uniform(0, math.tau)
        spd = random.uniform(2.5, 6.0) if fast else random.uniform(1.2, 3.5)
        self.x, self.y = x, y
        self.vx = math.cos(ang) * spd
        self.vy = math.sin(ang) * spd
        self.life = random.randint(12, 24)
        self.col = random.choice([7, 10, 10, 9])

    def update(self):
        self.x += self.vx
        self.y += self.vy
        self.vx *= 0.85
        self.vy *= 0.85
        self.life -= 1

    def draw(self):
        if self.life <= 0:
            return
        pyxel.line(self.x, self.y, self.x - self.vx, self.y - self.vy, self.col)


class Slash:
    """ビート同期の斬撃。hit_frame に PARRY_POINT 到達。note を持つ。"""
    def __init__(self, hit_frame, note):
        self.hit_frame = hit_frame
        self.note = note
        self.resolved = False

    def x_at(self, bf):
        return PARRY_POINT - (self.hit_frame - bf) * SLASH_SPEED


class Game:
    def __init__(self):
        pyxel.init(W, H, title="RHYTHM PARRY", fps=60)
        self._sounds()
        self.active_frames = ACTIVE_FRAMES
        self.window_flash = 0
        self.reset()
        pyxel.run(self.update, self.draw)

    def _sounds(self):
        # ファミコン4音源構成
        pyxel.sounds[1].set("c3e3g3",   "s", "7",  "f",  4)   # リード旋律(動的上書き)
        pyxel.sounds[2].set("c1",       "t", "6",  "n",  30)  # ベース(動的上書き)
        pyxel.sounds[3].set("f1c1",     "n", "7",  "ff", 16)  # 被弾
        pyxel.sounds[4].set("d3",       "n", "6",  "f",  4)   # スネア
        pyxel.sounds[5].set("a3f3c3a2", "s", "6",  "f",  18)  # ゲームオーバー
        pyxel.sounds[6].set("c1",       "t", "6",  "f",  5)   # キック
        pyxel.sounds[7].set("f4",       "n", "2",  "f",  2)   # ハイハット
        pyxel.sounds[8].set("c4e4g4",   "s", "5",  "f",  2)   # PERFECT装飾(高音きらめき)

    def reset(self):
        self.hp = MAX_HP
        self.combo = 0
        self.best_combo = 0
        self.score = 0
        self.perfects = 0
        self.slashes = []
        self.beat_frame = -1
        self.blade_cd = 0
        self.blade_flash = 0
        self.blade_col = 7
        self.beat_pulse = 0
        self.sparks = []
        self.shake = 0
        self.flash = 0
        self.hurt = 0
        self.miss_flash = 0
        self.result_text = ""
        self.result_col = 7
        self.result_timer = 0
        self.enemy_lunge = 0
        self.enemy_recoil = 0
        self.over = False
        self.time_left = TIME_LIMIT
        self.end_reason = ""

    # ---------- 入力・調整 ----------
    def _read_parry(self):
        pressed = (pyxel.btnp(pyxel.KEY_SPACE) or pyxel.btnp(pyxel.KEY_Z)
                   or pyxel.btnp(pyxel.KEY_X))
        if not pressed or self.blade_cd > 0:
            return
        self.blade_cd = COOLDOWN
        self.blade_flash = 6
        cand = [s for s in self.slashes if not s.resolved]
        if not cand:
            self.blade_col = 6
            return
        s = min(cand, key=lambda s: abs(s.hit_frame - self.beat_frame))
        diff = abs(s.hit_frame - self.beat_frame)
        if diff <= self.active_frames:
            self._do_parry(s, diff <= PERFECT_LATE)
        else:
            self.blade_col = 6

    def _adjust_window(self):
        inc = (pyxel.btnp(pyxel.KEY_RIGHT, hold=14, repeat=4)
               or pyxel.btnp(pyxel.KEY_UP, hold=14, repeat=4))
        dec = (pyxel.btnp(pyxel.KEY_LEFT, hold=14, repeat=4)
               or pyxel.btnp(pyxel.KEY_DOWN, hold=14, repeat=4))
        if inc:
            self.active_frames = min(20, self.active_frames + 1)
            self.window_flash = 12
        if dec:
            self.active_frames = max(2, self.active_frames - 1)
            self.window_flash = 12

    # ---------- ビート進行(伴奏) ----------
    def _on_step(self, step):
        if step % STEPS_PER_BEAT == 0:               # 下拍
            beat = step // STEPS_PER_BEAT
            # キック/スネアでバックビート(2・4拍にスネア)
            if (beat % 2) == 0:
                pyxel.play(3, 6)                     # キック
            else:
                pyxel.play(3, 4)                     # スネア
            # ベース
            pyxel.sounds[2].set(BASS[beat % len(BASS)], "t", "6", "n", 30)
            pyxel.play(2, 2)
            self.beat_pulse = 8
        else:                                        # 裏拍
            lp = step % len(MELODY)
            pyxel.play(3, 4 if lp >= 29 else 7)      # ループ直前はスネアでフィル

        # LOOKAHEAD先のステップに音があれば斬撃発生(その音を背負わせる)
        fi = (step + LOOKAHEAD_STEPS) % len(MELODY)
        note = MELODY[fi]
        if note != ".":
            self.slashes.append(
                Slash((step + LOOKAHEAD_STEPS) * FRAMES_PER_STEP, note))
            self.enemy_lunge = 8

    # ---------- 結果処理 ----------
    def _do_parry(self, s, perfect):
        s.resolved = True
        if s in self.slashes:
            self.slashes.remove(s)
        self.combo += 1
        self.best_combo = max(self.best_combo, self.combo)
        self.blade_col = 10 if perfect else 7

        ix, iy = PARRY_POINT, H // 2
        for _ in range(16 if perfect else 10):
            self.sparks.append(Spark(ix, iy, fast=perfect))
        self.shake = 6 if perfect else 3
        self.flash = 4 if perfect else 2
        self.enemy_recoil = 10

        if perfect:
            self.perfects += 1
            self.score += 100 * max(1, self.combo)
            self.result_text, self.result_col = "PERFECT!", 10
        else:
            self.score += 30 * max(1, self.combo)
            self.result_text, self.result_col = "PARRY", 7
        self.result_timer = 22

        # プレイヤーが「演奏する」音 — 単音ではなくコードの高速アルペジオで鳴らす
        arp = ARP.get(s.note, s.note)
        pyxel.sounds[1].set(arp, "s", "7", "f", 4)   # 矩形波の和音シマー+減衰
        pyxel.play(1, 1)
        if perfect:
            pyxel.play(0, 8)                         # 上に高音のきらめきを重ねる

    def _do_hit(self, s):
        s.resolved = True
        if s in self.slashes:
            self.slashes.remove(s)
        self.combo = 0
        self.hp -= 1
        self.shake = 10
        self.hurt = 8
        self.miss_flash = 16
        pyxel.play(0, 3)
        if self.hp <= 0:
            self.over = True
            self.end_reason = "DEFEATED"
            pyxel.play(0, 5)

    # ---------------- UPDATE ----------------
    def update(self):
        if self.flash > 0:        self.flash -= 1
        if self.shake > 0:        self.shake -= 1
        if self.hurt > 0:         self.hurt -= 1
        if self.miss_flash > 0:   self.miss_flash -= 1
        if self.result_timer > 0: self.result_timer -= 1
        if self.enemy_lunge > 0:  self.enemy_lunge -= 1
        if self.enemy_recoil > 0: self.enemy_recoil -= 1
        if self.blade_flash > 0:  self.blade_flash -= 1
        if self.beat_pulse > 0:   self.beat_pulse -= 1
        if self.window_flash > 0: self.window_flash -= 1
        for sp in self.sparks[:]:
            sp.update()
            if sp.life <= 0:
                self.sparks.remove(sp)

        self._adjust_window()

        if self.over:
            if pyxel.btnp(pyxel.KEY_R) or pyxel.btnp(pyxel.KEY_SPACE):
                self.reset()
            return

        self.time_left -= 1
        if self.time_left <= 0:
            self.time_left = 0
            self.over = True
            self.end_reason = "TIME UP"
            pyxel.play(0, 5)
            return

        # 一定テンポ死守(止めない)
        self.beat_frame += 1
        if self.beat_frame % FRAMES_PER_STEP == 0:
            self._on_step(self.beat_frame // FRAMES_PER_STEP)

        if self.blade_cd > 0:
            self.blade_cd -= 1
        self._read_parry()

        for s in self.slashes[:]:
            if s.resolved:
                self.slashes.remove(s)
                continue
            if self.beat_frame - s.hit_frame > self.active_frames:
                self._do_hit(s)

    # ---------------- DRAW ----------------
    def draw(self):
        ox = random.randint(-self.shake, self.shake) if self.shake else 0
        oy = random.randint(-self.shake, self.shake) if self.shake else 0
        pyxel.camera(ox, oy)

        pyxel.cls(0)
        pyxel.rect(0, H // 2 + 16, W, H, 1)

        if self.combo >= 3:
            n = min(self.combo, 12)
            for i in range(n):
                a = (i / n) * math.tau + pyxel.frame_count * 0.05
                pyxel.line(W // 2, H // 2,
                           W // 2 + math.cos(a) * 90,
                           H // 2 + math.sin(a) * 90, 5)

        pcol = 7 if self.beat_pulse > 4 else 5
        for y in range(0, H, 5):
            pyxel.pset(PARRY_POINT, y, pcol)
        if self.beat_pulse > 0:
            pyxel.circb(PARRY_POINT, H // 2, 2 + (8 - self.beat_pulse) * 2, 5)

        cy = H // 2
        self._draw_enemy(22 - self.enemy_recoil + self.enemy_lunge, cy)
        for s in self.slashes:
            x = s.x_at(self.beat_frame)
            if -10 < x < W + 10:
                self._draw_slash(x, cy)
        self._draw_player(100, cy)

        for sp in self.sparks:
            sp.draw()

        if self.flash > 1:
            pyxel.rect(0, 0, W, H, 7)

        pyxel.camera()
        if self.hurt > 0:
            pyxel.rectb(0, 0, W, H, 8)

        self._draw_hud()
        if self.over:
            self._draw_over()

    def _draw_enemy(self, x, y):
        pyxel.elli(x - 9, y - 9, 18, 18, 2)
        pyxel.tri(x - 7, y - 7, x - 4, y - 15, x - 1, y - 7, 2)
        pyxel.tri(x + 1, y - 7, x + 4, y - 15, x + 7, y - 7, 2)
        pyxel.rect(x - 5, y - 2, 3, 3, 8)
        pyxel.rect(x + 2, y - 2, 3, 3, 8)

    def _draw_slash(self, x, y):
        for i in range(-2, 3):
            c = 10 if i == 0 else (7 if abs(i) == 1 else 9)
            pyxel.line(x - 9 + i, y - 13, x + 9 + i, y + 13, c)
        pyxel.circ(x, y, 2, 7)

    def _draw_player(self, x, y):
        pyxel.rect(x, y - 8, 8, 16, 12)
        pyxel.rect(x + 1, y - 13, 6, 6, 15)
        pyxel.pset(x + 2, y - 11, 0)
        if self.blade_flash > 0:
            for a in range(-50, 51, 7):
                rad = math.radians(a)
                pyxel.pset(x - 3 - math.cos(rad) * 15, y - math.sin(rad) * 15,
                           self.blade_col)
        else:
            pyxel.line(x - 1, y - 2, x - 9, y - 11, 6)

    def _draw_hud(self):
        if not self.over:
            frac = self.time_left / TIME_LIMIT
            urgent = self.time_left < 5 * 60
            bcol = 8 if (urgent and pyxel.frame_count % 8 < 4) else 12
            pyxel.rect(0, 0, int(W * frac), 2, bcol)
            secs = (self.time_left + 59) // 60
            st = f"{secs}"
            pyxel.text(W // 2 - len(st) * 2, 4, st, 8 if urgent else 7)
            dc = 10 if self.beat_pulse > 4 else 5
            pyxel.circ(W // 2 + 12, 6, 2, dc)

        for i in range(MAX_HP):
            c = 8 if i < self.hp else 5
            hx = 4 + i * 9
            pyxel.tri(hx, 7, hx + 3, 4, hx + 6, 7, c)
            pyxel.tri(hx, 7, hx + 3, 11, hx + 6, 7, c)

        sc = str(self.score)
        pyxel.text(W - 4 - len(sc) * 4, 4, sc, 7)

        if self.combo > 1:
            s = f"{self.combo} CHAIN"
            tx = W // 2 - len(s) * 2
            col = 10 if self.combo >= 5 else 7
            pyxel.text(tx + 1, 19, s, 0)
            pyxel.text(tx, 18, s, col)

        if self.miss_flash > 0 and not self.over:
            m = "MISS"
            pyxel.text(W // 2 - len(m) * 2, 30, m, 8)

        if self.result_timer > 0:
            t = self.result_text
            yoff = (22 - self.result_timer) // 4
            tx = W // 2 - len(t) * 2
            pyxel.text(tx + 1, 41 - yoff, t, 0)
            pyxel.text(tx, 40 - yoff, t, self.result_col)

        wcol = 10 if self.window_flash > 0 else 12
        pyxel.text(4, H - 8, f"{self.active_frames}F WIN", wcol)
        pyxel.text(W // 2 - 14, H - 8, f"BPM {BPM}", 5)
        ad = "< > ADJ"
        pyxel.text(W - 4 - len(ad) * 4, H - 8, ad, 5)

        if self.combo == 0 and self.best_combo == 0 and not self.over:
            hint = "SPACE ON THE BEAT"
            c = 6 if pyxel.frame_count % 30 < 20 else 5
            pyxel.text(W // 2 - len(hint) * 2, H - 18, hint, c)

    def _draw_over(self):
        bx, by, bw, bh = 14, 30, W - 28, 68
        pyxel.rect(bx, by, bw, bh, 0)
        edge = 8 if self.end_reason == "DEFEATED" else 12
        pyxel.rectb(bx, by, bw, bh, edge)
        cx = W // 2
        title = self.end_reason or "TIME UP"
        tcol = 8 if self.end_reason == "DEFEATED" else 10
        pyxel.text(cx - len(title) * 2, by + 6, title, tcol)
        pyxel.line(bx + 4, by + 15, bx + bw - 5, by + 15, 5)
        rows = [
            (f"SCORE  {self.score}", 7),
            (f"PERFECT  {self.perfects}", 10),
            (f"BEST CHAIN  {self.best_combo}", 11),
        ]
        for i, (t, c) in enumerate(rows):
            pyxel.text(cx - len(t) * 2, by + 22 + i * 9, t, c)
        r = "R : RETRY"
        rc = 7 if pyxel.frame_count % 30 < 20 else 6
        pyxel.text(cx - len(r) * 2, by + bh - 11, r, rc)


Game()
