import json
import os
import queue
import random
import re
import sys
import threading
import tkinter as tk
import urllib.error
import urllib.request
from tkinter import messagebox, ttk

try:
    import chess
except ImportError:
    raise SystemExit("The 'python-chess' library is not installed. Please run, for example: pip install chess")

OLLAMA_URL = "http://localhost:11434/api/chat"
DEFAULT_MODEL = "llama3.2"

SQ = 80
MARGIN = 28
BG = "#2b2b2b"
PANEL_BG = "#333333"
FG = "#eeeeee"
ACCENT = "#7fa650"
LIGHT = "#f0d9b5"
DARK = "#b58863"
SELECT_COLOR = "#f6f669"
LAST_LIGHT = "#cdd26a"
LAST_DARK = "#aaa23a"
CHECK_COLOR = "#e8584f"
DOT_COLOR = "#6b8e3d"

GLYPHS = {
    chess.KING: "♚", chess.QUEEN: "♛", chess.ROOK: "♜",
    chess.BISHOP: "♝", chess.KNIGHT: "♞", chess.PAWN: "♟",
}

if sys.platform.startswith("win"):
    PIECE_FONT = "Segoe UI Symbol"
elif sys.platform == "darwin":
    PIECE_FONT = "Apple Symbols"
else:
    PIECE_FONT = "DejaVu Sans"


def ollama_move(board: chess.Board, model: str):
    """Просить модель Ollama зробити хід. Мережеві помилки передаються далі,
    щоб get_ai_move міг показати правильне повідомлення."""
    legal = [m.uci() for m in board.legal_moves]
    color = "white" if board.turn == chess.WHITE else "black"
    prompt = (
        f"You are playing chess as {color}.\n"
        f"Position (FEN): {board.fen()}\n"
        f"Legal moves (UCI): {', '.join(legal)}\n"
        "Choose the best move from the list. Answer ONLY with one move in UCI format, "
        "for example e2e4, without any explanations."
    )
    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "options": {"temperature": 0.3},
    }).encode("utf-8")
    req = urllib.request.Request(
        OLLAMA_URL, data=payload, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    answer = data.get("message", {}).get("content", "").lower()
    for token in re.findall(r"[a-h][1-8][a-h][1-8][qrbn]?", answer):
        if token in legal:
            return chess.Move.from_uci(token)
    return None


def get_ai_move(board: chess.Board, model: str):
    note = None
    for _ in range(3):
        try:
            move = ollama_move(board, model)
            if move:
                return move, None
            note = "The model made an invalid move — a random move was made instead."
        except urllib.error.URLError:
            note = "Cannot connect to Ollama (is it running?) — a random move was made instead."
            break
        except Exception as e:
            note = f"AI Error: {e}. A random move was made instead."
            break
    return random.choice(list(board.legal_moves)), note


def game_over_message(board: chess.Board) -> str:
    if board.is_checkmate():
        winner = "Black" if board.turn == chess.WHITE else "White"
        return f"Checkmate! {winner} wins."
    if board.is_stalemate():
        return "Stalemate. Draw."
    if board.is_insufficient_material():
        return "Draw due to insufficient material."
    if board.is_fifty_moves():
        return "Draw by 50-move rule."
    if board.is_repetition():
        return "Draw by threefold repetition."
    return "Game over."


class ChessApp(tk.Tk):
    def __init__(self):
        super().__init__()
        # Підганяємо розмір клітинки під висоту екрана (від 48 до 80 px)
        global SQ
        SQ = max(48, min(80, (self.winfo_screenheight() - 360 - 2 * MARGIN) // 8))
        if os.environ.get("CHESS_SQ", "").isdigit():
            SQ = int(os.environ["CHESS_SQ"])
        self.title("Chess")
        self.configure(bg=BG)
        self.resizable(False, False)

        self.setup_styles()

        self.board = chess.Board()
        self.vs_ai = False
        self.human_color = chess.WHITE
        self.model = DEFAULT_MODEL
        self.flip = False
        self.selected = None
        self.targets = []
        self.ai_thinking = False
        self.notice_shown = False
        self.game_id = 0
        self.ai_queue = queue.Queue()

        self.menu_frame: tk.Frame
        self.game_frame: tk.Frame
        self.build_menu()
        self.build_game()
        self.show_menu()

        self.after(100, self.poll_ai)

    def setup_styles(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(
            "Big.TButton", font=("Segoe UI", 15, "bold"), padding=14,
            background=ACCENT, foreground="white", borderwidth=0,
        )
        style.map("Big.TButton", background=[("active", "#8fbf5a")])
        style.configure(
            "Side.TButton", font=("Segoe UI", 11), padding=8,
            background="#4a4a4a", foreground=FG, borderwidth=0,
        )
        style.map("Side.TButton", background=[("active", "#5c5c5c"), ("disabled", "#3a3a3a")],
                  foreground=[("disabled", "#777777")])
        style.configure("Menu.TRadiobutton", background=BG, foreground=FG, font=("Segoe UI", 12))
        style.map("Menu.TRadiobutton", background=[("active", BG)])

    def build_menu(self):
        f = tk.Frame(self, bg=BG, padx=70, pady=40)
        self.menu_frame = f

        tk.Label(f, text="♞", font=(PIECE_FONT, 64), bg=BG, fg=ACCENT).pack()
        tk.Label(f, text="CHESS", font=("Segoe UI", 30, "bold"), bg=BG, fg=FG).pack(pady=(0, 24))

        ttk.Button(f, text="Play vs AI", style="Big.TButton",
                   command=lambda: self.start_game(True)).pack(fill="x", pady=6)
        ttk.Button(f, text="Play vs Friend", style="Big.TButton",
                   command=lambda: self.start_game(False)).pack(fill="x", pady=6)

        opts = tk.LabelFrame(f, text=" AI Settings ", bg=BG, fg="#aaaaaa",
                             font=("Segoe UI", 10), padx=14, pady=10, bd=1)
        opts.pack(fill="x", pady=(24, 6))

        self.color_var = tk.StringVar(value="white")
        row = tk.Frame(opts, bg=BG)
        row.pack(fill="x")
        tk.Label(row, text="Play as:", bg=BG, fg=FG, font=("Segoe UI", 12)).pack(side="left")
        ttk.Radiobutton(row, text="White", value="white", variable=self.color_var,
                        style="Menu.TRadiobutton").pack(side="left", padx=8)
        ttk.Radiobutton(row, text="Black", value="black", variable=self.color_var,
                        style="Menu.TRadiobutton").pack(side="left")

        row2 = tk.Frame(opts, bg=BG)
        row2.pack(fill="x", pady=(10, 0))
        tk.Label(row2, text="Model:", bg=BG, fg=FG, font=("Segoe UI", 12)).pack(side="left")
        self.model_var = tk.StringVar(value=DEFAULT_MODEL)
        tk.Entry(row2, textvariable=self.model_var, font=("Segoe UI", 12), width=18,
                 bg="#444444", fg=FG, insertbackground=FG, relief="flat").pack(side="left", padx=8)

        ttk.Button(f, text="Exit", style="Side.TButton", command=self.destroy).pack(
            fill="x", pady=(20, 0))

    def build_game(self):
        f = tk.Frame(self, bg=BG, padx=12, pady=12)
        self.game_frame = f

        size = 8 * SQ + 2 * MARGIN
        self.canvas = tk.Canvas(f, width=size, height=size, bg=BG, highlightthickness=0)
        self.canvas.grid(row=0, column=0, rowspan=2)
        self.canvas.bind("<Button-1>", self.on_click)

        panel = tk.Frame(f, bg=PANEL_BG, padx=14, pady=14, width=260)
        panel.grid(row=0, column=1, rowspan=2, sticky="ns", padx=(12, 0), pady=MARGIN)
        panel.grid_propagate(False)
        self.panel = panel

        self.mode_label = tk.Label(panel, text="", bg=PANEL_BG, fg="#aaaaaa", font=("Segoe UI", 10))
        self.mode_label.pack(anchor="w")
        self.status_label = tk.Label(panel, text="", bg=PANEL_BG, fg=FG, wraplength=230,
                                     justify="left", font=("Segoe UI", 14, "bold"))
        self.status_label.pack(anchor="w", pady=(4, 10))

        tk.Label(panel, text="Moves", bg=PANEL_BG, fg="#aaaaaa", font=("Segoe UI", 10)).pack(anchor="w")
        box = tk.Frame(panel, bg=PANEL_BG)
        box.pack(fill="both", expand=True)
        sb = ttk.Scrollbar(box)
        sb.pack(side="right", fill="y")

        self.moves_text = tk.Text(box, width=24, height=14, bg="#2a2a2a", fg=FG,
                                  font=("Consolas", 11), relief="flat", state="disabled",
                                  yscrollcommand=sb.set)
        self.moves_text.pack(side="left", fill="both", expand=True)
        sb.config(command=self.moves_text.yview)

        self.back_btn = ttk.Button(panel, text="Back to Menu", style="Side.TButton", command=self.show_menu)
        self.back_btn.pack(fill="x", pady=(14, 0))

    def show_menu(self):
        self.game_frame.pack_forget()
        self.menu_frame.pack()

    def start_game(self, vs_ai: bool):
        self.menu_frame.pack_forget()
        self.game_frame.pack()

        self.board = chess.Board()
        self.vs_ai = vs_ai
        self.game_id += 1
        self.selected = None
        self.targets = []
        self.ai_thinking = False
        self.notice_shown = False

        if vs_ai:
            self.human_color = chess.WHITE if self.color_var.get() == "white" else chess.BLACK
            self.model = self.model_var.get().strip() or DEFAULT_MODEL
            self.flip = (self.human_color == chess.BLACK)
            self.mode_label.config(text=f"VS AI ({self.model})")
        else:
            self.flip = False
            self.mode_label.config(text="VS Friend")

        self.back_btn.config(state="normal")
        self.update_moves_list()
        self.draw_board()
        self.check_ai_trigger()

    def square_from_cell(self, c, r):
        """Перетворює клітинку на екрані (стовпець c, рядок r) у поле шахівниці."""
        if self.flip:
            return chess.square(7 - c, r)
        return chess.square(c, 7 - r)

    def draw_board(self):
        self.canvas.delete("all")

        last = self.board.move_stack[-1] if self.board.move_stack else None
        in_check = self.board.is_check()
        king_in_check = self.board.king(self.board.turn) if in_check else None

        # 1. Малюємо клітинки дошки
        for r in range(8):
            for c in range(8):
                square = self.square_from_cell(c, r)
                is_light = (r + c) % 2 == 0

                # Базові кольори
                color = LIGHT if is_light else DARK

                # Підсвічування останнього ходу
                if last and square in (last.from_square, last.to_square):
                    color = LAST_LIGHT if is_light else LAST_DARK

                # Підсвічування виділеної фігури
                if self.selected == square:
                    color = SELECT_COLOR

                # Підсвічування шаху королю
                if king_in_check is not None and square == king_in_check:
                    color = CHECK_COLOR

                x1 = MARGIN + c * SQ
                y1 = MARGIN + r * SQ
                self.canvas.create_rectangle(x1, y1, x1 + SQ, y1 + SQ, fill=color, outline="")

                # Малювання крапок для можливих ходів
                if square in self.targets:
                    cx, cy = x1 + SQ // 2, y1 + SQ // 2
                    if self.board.piece_at(square) or self.board.is_en_passant(
                            chess.Move(self.selected, square)):
                        self.canvas.create_oval(x1 + 4, y1 + 4, x1 + SQ - 4, y1 + SQ - 4,
                                                outline=DOT_COLOR, width=4)
                    else:
                        self.canvas.create_oval(cx - 10, cy - 10, cx + 10, cy + 10,
                                                fill=DOT_COLOR, outline="")

        # 2. Малюємо координати (літери та цифри)
        files = "abcdefgh" if not self.flip else "hgfedcba"
        ranks = "87654321" if not self.flip else "12345678"
        for i in range(8):
            # Літери (зверху і знизу)
            self.canvas.create_text(MARGIN + i * SQ + SQ // 2, MARGIN // 2,
                                    text=files[i], fill="#777777", font=("Segoe UI", 10))
            self.canvas.create_text(MARGIN + i * SQ + SQ // 2, MARGIN + 8 * SQ + MARGIN // 2,
                                    text=files[i], fill="#777777", font=("Segoe UI", 10))
            # Цифри (зліва і справа)
            self.canvas.create_text(MARGIN // 2, MARGIN + i * SQ + SQ // 2,
                                    text=ranks[i], fill="#777777", font=("Segoe UI", 10))
            self.canvas.create_text(MARGIN + 8 * SQ + MARGIN // 2, MARGIN + i * SQ + SQ // 2,
                                    text=ranks[i], fill="#777777", font=("Segoe UI", 10))

        # 3. Малюємо фігури
        for square in chess.SQUARES:
            piece = self.board.piece_at(square)
            if piece:
                file_ = chess.square_file(square)
                rank_ = chess.square_rank(square)
                c = file_ if not self.flip else 7 - file_
                r = 7 - rank_ if not self.flip else rank_
                x = MARGIN + c * SQ + SQ // 2
                y = MARGIN + r * SQ + SQ // 2
                glyph = GLYPHS[piece.piece_type]
                p_color = "#ffffff" if piece.color == chess.WHITE else "#000000"
                self.canvas.create_text(x, y, text=glyph, font=(PIECE_FONT, int(SQ * 0.55)), fill=p_color)

        # 4. Оновлюємо статус гри на бічній панелі
        if self.board.is_game_over():
            self.status_label.config(text=game_over_message(self.board))
        elif self.ai_thinking:
            self.status_label.config(text="AI is thinking...")
        else:
            turn_str = "White's turn" if self.board.turn == chess.WHITE else "Black's turn"
            self.status_label.config(text=turn_str)

    def on_click(self, event):
        if self.board.is_game_over() or self.ai_thinking:
            return

        c = (event.x - MARGIN) // SQ
        r = (event.y - MARGIN) // SQ
        if not (0 <= c < 8 and 0 <= r < 8):
            return

        square = self.square_from_cell(c, r)

        if self.selected is not None and square in self.targets:
            move = chess.Move(self.selected, square)
            # Автоматичне перетворення пішака на Ферзя на останній горизонталі
            piece = self.board.piece_at(self.selected)
            if piece and piece.piece_type == chess.PAWN:
                if chess.square_rank(square) in (0, 7):
                    move.promotion = chess.QUEEN

            self.board.push(move)
            self.selected = None
            self.targets = []
            self.update_moves_list()
            self.draw_board()

            if not self.board.is_game_over():
                self.check_ai_trigger()
        else:
            piece = self.board.piece_at(square)
            if piece and piece.color == self.board.turn:
                if self.vs_ai and piece.color != self.human_color:
                    return
                self.selected = square
                self.targets = [m.to_square for m in self.board.legal_moves
                                if m.from_square == square]
            else:
                self.selected = None
                self.targets = []
            self.draw_board()

    def check_ai_trigger(self):
        if self.vs_ai and not self.board.is_game_over() and self.board.turn != self.human_color:
            self.ai_thinking = True
            self.back_btn.config(state="disabled")
            self.draw_board()
            threading.Thread(
                target=self.bg_ai_worker,
                args=(self.game_id, self.board.copy(), self.model),
                daemon=True
            ).start()

    def bg_ai_worker(self, gid, board_copy, model):
        move, note = get_ai_move(board_copy, model)
        self.ai_queue.put((gid, move, note))

    def poll_ai(self):
        try:
            while True:
                gid, move, note = self.ai_queue.get_nowait()
                if gid == self.game_id and self.ai_thinking:
                    self.ai_thinking = False
                    self.back_btn.config(state="normal")
                    self.board.push(move)
                    self.update_moves_list()
                    self.draw_board()
                    if note and not self.notice_shown:
                        self.notice_shown = True
                        self.after(10, lambda n=note: messagebox.showinfo("AI Notice", n))
        except queue.Empty:
            pass
        self.after(100, self.poll_ai)

    def update_moves_list(self):
        self.moves_text.config(state="normal")
        self.moves_text.delete("1.0", tk.END)

        temp_board = chess.Board()
        lines = []
        for i, move in enumerate(self.board.move_stack):
            san = temp_board.san(move)
            temp_board.push(move)
            if i % 2 == 0:
                lines.append(f"{i // 2 + 1:2d}. {san:<8}")
            else:
                lines[-1] += f" {san}"

        self.moves_text.insert("1.0", "\n".join(lines))
        self.moves_text.config(state="disabled")
        self.moves_text.see(tk.END)


if __name__ == "__main__":
    app = ChessApp()
    app.mainloop()