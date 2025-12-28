# app.py
from __future__ import annotations

import os
import subprocess
import sys
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Dict, Optional

import tkinter as tk
from tkinter import END, Menu, StringVar, IntVar, Toplevel, messagebox, filedialog
from tkinter import ttk
import tkinter.font as tkfont

from db import (
    DB_PATH,
    init_db, available_years, list_clientes, list_by_month_year,
    sum_lucro, insert_cliente, update_cliente, delete_cliente, flights_departing_on,
)
from utils import (
    br_to_iso, iso_to_br, parse_currency_to_cents, format_cents_br,
    valido_cpf, somente_digitos,
    
)


class App:
    # ====== Tamanhos fixos dos boxes (ajuste aqui se precisar) ======
    FORM_W = 560
    FORM_H = 760
    TABLE_W = 1000
    TABLE_H = 760

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Agência de Viagens — CRM de Clientes")
        self.root.geometry("1600x980")
        self.root.minsize(1280, 860)

        self.base_font = "Segoe UI"
        self.base_size = 11

        self._masking_guard = False  # evita recursão nos formatadores
        self.var_lucro_mode = tk.StringVar(value="cliente")  # 'custo' ou 'cliente' (padrão corrige estornos reduzindo lucro)

        self._make_styles()
        self._init_vars()
        self._build_layout()
        self.refresh_year_month_options()
        self.refresh_table()
        self.update_totals()

        # Checagem inicial e periódica de voos de amanhã
        self.check_upcoming_flights(show_if_empty=False)
        self.schedule_hourly_check()

        # Atalhos
        self.root.bind("<Control-n>", lambda _e: self.on_clear_form())
        self.root.bind("<Control-s>", lambda _e: self.on_save())
        self.root.bind("<Delete>", lambda _e: self.on_delete())
        # fonte +/-
        self.root.bind("<Control-plus>", lambda _e: self.increase_font())
        self.root.bind("<Control-KP_Add>", lambda _e: self.increase_font())
        self.root.bind("<Control-=>", lambda _e: self.increase_font())
        self.root.bind("<Control-minus>", lambda _e: self.decrease_font())
        self.root.bind("<Control-KP_Subtract>", lambda _e: self.decrease_font())

    # ---------- Estilos ----------
    def _make_styles(self) -> None:
        self.style = getattr(self, "style", ttk.Style(self.root))
        try:
            self.style.theme_use("clam")
        except Exception:
            pass

        self.colors = {
            "bg": "#F3F4F6",
            "fg": "#1F2937",
            "card": "#FFFFFF",
            "border": "#D1D5DB",
            "accent": "#0EA5A4",
            "accent_fg": "#FFFFFF",
            "muted": "#4B5563",
            "row_odd": "#FFFFFF",
            "row_even": "#F3F4F6",
            "row_sel": "#D1FAE5",
        }
        c = self.colors

        base_font = (self.base_font, self.base_size)
        header_font = (self.base_font, self.base_size + 2, "bold")
        field_font = (self.base_font, self.base_size)
        tree_heading_font = (self.base_font, self.base_size, "bold")

        self.style.configure("TFrame", background=c["bg"])
        self.root.configure(bg=c["bg"])

        self.style.configure("TLabel", background=c["bg"], foreground=c["fg"], font=base_font)
        self.style.configure("Header.TLabel", background=c["bg"], foreground=c["fg"], font=header_font)
        self.style.configure("Field.TLabel", background=c["bg"], foreground=c["muted"], font=field_font)
        self.style.configure("TButton", font=base_font, padding=10)

        self.style.configure(
            "TLabelframe",
            background=c["card"],
            bordercolor=c["border"],
            borderwidth=1,
            relief="solid",
        )
        self.style.configure(
            "TLabelframe.Label",
            background=c["card"],
            foreground=c["fg"],
            font=(self.base_font, self.base_size + 1, "bold"),
        )
        self.style.configure("TEntry", padding=8, fieldbackground="#FFFFFF", foreground=c["fg"])
        self.style.configure("TCombobox", padding=8)

        self.style.configure("Treeview", background=c["card"], fieldbackground=c["card"], foreground=c["fg"], rowheight=32)
        self.style.configure("Treeview.Heading", background=c["card"], foreground=c["fg"], font=tree_heading_font)
        self.style.map("Treeview", background=[("selected", c["row_sel"])])

        self.style.configure("Status.TLabel", background=c["bg"], foreground=c["muted"], font=(self.base_font, self.base_size - 1))

        if hasattr(self, "tree"):
            self.tree.configure()

    # ---------- Controle de fonte ----------
    def apply_font_size(self, new_size: int) -> None:
        new_size = max(9, min(18, int(new_size)))
        if new_size == self.base_size:
            return
        self.base_size = new_size
        self._make_styles()
        if hasattr(self, "_headings") and hasattr(self, "tree"):
            for c in self._headings:
                current = self.tree.heading(c)["text"]
                self.tree.heading(c, text=current or self._headings[c])
        if hasattr(self, "tree"):
            self._auto_adjust_all_columns(self.tree)

    def increase_font(self) -> None:
        self.apply_font_size(self.base_size + 1)

    def decrease_font(self) -> None:
        self.apply_font_size(self.base_size - 1)

    # ---------- State ----------
    def _init_vars(self) -> None:
        self.var_id = IntVar(value=0)
        self.var_nome = StringVar()
        self.var_nascimento = StringVar()
        self.var_compra = StringVar()
        self.var_doc_tipo = StringVar(value="CPF")
        self.var_doc_valor = StringVar()
        self.var_valor_venda = StringVar()
        self.var_valor_lucro = StringVar()
        self.var_valor_pago = StringVar()
        self.var_data_ida = StringVar()
        self.var_data_volta = StringVar()
        self.var_doc_voo_path = StringVar()

        self.var_busca = StringVar()
        self.var_ano = StringVar()
        self.var_mes = StringVar(value="Todos")

        self.col_sort_state = {k: (k != "id") for k in ["id","nome","nascimento","compra","ida","volta","doc","venda","pago","lucro"]}
        self.col_sort_state["id"] = False
        self._lucro_user_edited = False

    # ---------- Auto-ajuste colunas ----------
    def _get_tree_font(self, tree: ttk.Treeview) -> tkfont.Font:
        try:
            font_name = self.style.lookup("Treeview", "font")
            if font_name:
                return tkfont.nametofont(font_name)
        except Exception:
            pass
        return tkfont.Font(family=self.base_font, size=self.base_size)

    def _auto_adjust_column(
        self,
        tree: ttk.Treeview,
        col: str,
        *,
        min_w: int = 60,
        max_w: int = 520,
        padding: int = 24,
    ) -> None:
        """
        Ajusta a largura da coluna medindo o texto (células + cabeçalho).
        Para colunas de moeda (venda/pago/lucro) o limite máximo é elevado.
        """
        if col in {"venda", "pago", "lucro"}:
            max_w = 1200  # <- permite exibir valores altos sem truncar

        f = self._get_tree_font(tree)
        heading_text = tree.heading(col).get("text", "")
        max_width = f.measure(heading_text) + padding

        for iid in tree.get_children(""):
            txt = str(tree.set(iid, col))
            w = f.measure(txt)
            if w + padding > max_width:
                max_width = w + padding

        max_width = max(min_w, min(max_w, max_width))
        tree.column(col, width=max_width)

    def _auto_adjust_all_columns(self, tree: ttk.Treeview) -> None:
        for col in tree["columns"]:
            self._auto_adjust_column(tree, col)

    # ---------- Layout ----------
    def _build_layout(self) -> None:
        # Menu
        menubar = Menu(self.root)
        menu_banco = Menu(menubar, tearoff=False)
        menu_banco.add_command(label="Trocar banco de dados…", command=self.on_change_db)
        menu_banco.add_command(label="Mostrar caminho do banco", command=self.on_show_db_path)
        menubar.add_cascade(label="Banco", menu=menu_banco)

        # ===== Modo de cálculo do Lucro =====
        menu_lucro = Menu(menubar, tearoff=False)
        menu_lucro.add_radiobutton(
            label="Pago é Custo  →  Lucro = Venda - Pago",
            variable=self.var_lucro_mode,
            value="custo",
            command=self.on_change_lucro_mode,
        )
        menu_lucro.add_radiobutton(
            label="Pago é do Cliente  →  Lucro = Venda + Pago",
            variable=self.var_lucro_mode,
            value="cliente",
            command=self.on_change_lucro_mode,
        )
        menubar.add_cascade(label="Lucro", menu=menu_lucro)

        menu_view = Menu(menubar, tearoff=False)
        menu_view.add_command(label="Aumentar fonte\tCtrl++", command=self.increase_font)
        menu_view.add_command(label="Diminuir fonte\tCtrl+-", command=self.decrease_font)
        menubar.add_cascade(label="Exibir", menu=menu_view)
        self.root.config(menu=menubar)

        # Topbar
        top = ttk.Frame(self.root, padding=(16, 12))
        top.pack(side="top", fill="x")

        ttk.Label(top, text="Buscar (Nome/Documento):", style="Field.TLabel").grid(row=0, column=0, sticky="e")
        ent_busca = ttk.Entry(top, textvariable=self.var_busca, width=40)
        ent_busca.grid(row=0, column=1, sticky="w", padx=(6, 12))
        ttk.Button(top, text="Aplicar", command=self.on_apply_search).grid(row=0, column=2)
        ttk.Button(top, text="Limpar", command=self.on_clear_search).grid(row=0, column=3, padx=(6, 18))

        ttk.Label(top, text="Ano:", style="Field.TLabel").grid(row=0, column=4, sticky="e")
        self.cmb_ano = ttk.Combobox(top, textvariable=self.var_ano, width=8, state="readonly")
        self.cmb_ano.grid(row=0, column=5, sticky="w", padx=(6, 0))

        ttk.Label(top, text="Mês:", style="Field.TLabel").grid(row=0, column=6, sticky="e", padx=(12, 0))
        self.cmb_mes = ttk.Combobox(
            top,
            textvariable=self.var_mes,
            width=12,
            state="readonly",
            values=["Todos","Janeiro","Fevereiro","Março","Abril","Maio","Junho","Julho","Agosto","Setembro","Outubro","Novembro","Dezembro"],
        )
        self.cmb_mes.grid(row=0, column=7, sticky="w", padx=(6, 0))
        self.cmb_ano.bind("<<ComboboxSelected>>", lambda _e: self.update_totals())
        self.cmb_mes.bind("<<ComboboxSelected>>", lambda _e: self.update_totals())

        self.lbl_total_mes = ttk.Label(top, text="Total (Mês): —", style="Header.TLabel")
        self.lbl_total_mes.grid(row=0, column=8, padx=(24, 12), sticky="w")
        self.lbl_total_ano = ttk.Label(top, text="Total (Ano): R$ 0,00", style="Header.TLabel")
        self.lbl_total_ano.grid(row=0, column=9, sticky="w")

        ttk.Button(top, text="Vendas por Mês/Ano…", command=self.open_month_year_view).grid(row=0, column=10, padx=(18, 0))
        ttk.Button(top, text="Checar voos de amanhã", command=lambda: self.check_upcoming_flights(show_if_empty=True)).grid(row=0, column=11, padx=(12, 0))
        top.grid_columnconfigure(1, weight=1)

        # ======= ÁREA PRINCIPAL =======
        body = ttk.Frame(self.root)
        body.pack(fill="both", expand=True, padx=0, pady=0)

        center_frame = ttk.Frame(body)
        center_frame.place(relx=0.5, rely=0.5, anchor="center")

        # Formulário - box fixa
        form = ttk.LabelFrame(center_frame, text="Formulário do Cliente", padding=16,
                              width=self.FORM_W, height=self.FORM_H)
        form.pack(side="left", padx=(0, 12))
        form.pack_propagate(False)

        # Tabela - box fixa
        table_frame = ttk.LabelFrame(center_frame, text="Clientes", padding=10,
                                     width=self.TABLE_W, height=self.TABLE_H)
        table_frame.pack(side="left")
        table_frame.pack_propagate(False)

        # ---- Conteúdo do formulário ----
        r = 0
        ttk.Label(form, text="ID", style="Field.TLabel").grid(row=r, column=0, sticky="e", pady=4, padx=(0, 8))
        self.lbl_id = ttk.Label(form, textvariable=self.var_id)
        self.lbl_id.grid(row=r, column=1, sticky="w", pady=4)

        r += 1
        ttk.Label(form, text="Nome completo *", style="Field.TLabel").grid(row=r, column=0, sticky="e", pady=4, padx=(0, 8))
        self.ent_nome = ttk.Entry(form, textvariable=self.var_nome, width=36); self.ent_nome.grid(row=r, column=1, sticky="w", pady=4)

        r += 1
        ttk.Label(form, text="Data de nascimento *", style="Field.TLabel").grid(row=r, column=0, sticky="e", pady=4, padx=(0, 8))
        self.ent_nascimento = ttk.Entry(form, textvariable=self.var_nascimento, width=14); self.ent_nascimento.grid(row=r, column=1, sticky="w", pady=4)

        r += 1
        ttk.Label(form, text="Data de compra *", style="Field.TLabel").grid(row=r, column=0, sticky="e", pady=4, padx=(0, 8))
        self.ent_compra = ttk.Entry(form, textvariable=self.var_compra, width=14); self.ent_compra.grid(row=r, column=1, sticky="w", pady=4)

        r += 1
        ttk.Label(form, text="Data de ida *", style="Field.TLabel").grid(row=r, column=0, sticky="e", pady=4, padx=(0, 8))
        self.ent_ida = ttk.Entry(form, textvariable=self.var_data_ida, width=14); self.ent_ida.grid(row=r, column=1, sticky="w", pady=4)

        r += 1
        ttk.Label(form, text="Data de volta", style="Field.TLabel").grid(row=r, column=0, sticky="e", pady=4, padx=(0, 8))
        self.ent_volta = ttk.Entry(form, textvariable=self.var_data_volta, width=14); self.ent_volta.grid(row=r, column=1, sticky="w", pady=4)
        ttk.Label(form, text="(opcional)").grid(row=r, column=2, sticky="w")

        r += 1
        ttk.Label(form, text="Documento *", style="Field.TLabel").grid(row=r, column=0, sticky="e", pady=4, padx=(0, 8))
        ttk.Combobox(form, textvariable=self.var_doc_tipo, values=["CPF", "Passaporte"], state="readonly", width=12).grid(row=r, column=1, sticky="w", pady=4)

        r += 1
        ttk.Label(form, text="Número do Documento *", style="Field.TLabel").grid(row=r, column=0, sticky="e", pady=4, padx=(0, 8))
        self.ent_doc_valor = ttk.Entry(form, textvariable=self.var_doc_valor, width=24); self.ent_doc_valor.grid(row=r, column=1, sticky="w", pady=4)

        r += 1
        ttk.Label(form, text="Valor de compra *", style="Field.TLabel").grid(row=r, column=0, sticky="e", pady=4, padx=(0, 8))
        self.ent_venda = ttk.Entry(form, textvariable=self.var_valor_venda, width=18); self.ent_venda.grid(row=r, column=1, sticky="w", pady=4)
        self.ent_venda.bind("<KeyRelease>", self.on_price_change)

        r += 1
        ttk.Label(form, text="Valor pago (cliente)", style="Field.TLabel").grid(row=r, column=0, sticky="e", pady=4, padx=(0, 8))
        self.ent_pago = ttk.Entry(form, textvariable=self.var_valor_pago, width=18); self.ent_pago.grid(row=r, column=1, sticky="w", pady=4)
        ttk.Label(form, text="(opcional)").grid(row=r, column=2, sticky="w")
        self.ent_pago.bind("<KeyRelease>", self.on_price_change)

        r += 1
        ttk.Label(form, text="Valor lucrado *", style="Field.TLabel").grid(row=r, column=0, sticky="e", pady=4, padx=(0, 8))
        row_lucro = ttk.Frame(form); row_lucro.grid(row=r, column=1, sticky="w")
        self.ent_lucro = ttk.Entry(row_lucro, textvariable=self.var_valor_lucro, width=18); self.ent_lucro.pack(side="left")
        self.ent_lucro.bind("<KeyRelease>", self.on_lucro_edited); self.ent_lucro.bind("<FocusIn>", self.on_lucro_edited)
        btn_recalc = ttk.Button(row_lucro, text="↻", width=3, command=self.on_recalc_lucro); btn_recalc.pack(side="left", padx=8)
        self._attach_tooltip(btn_recalc, "Recalcular (modo atual do menu Lucro)")

        r += 1
        ttk.Label(form, text="Documento do voo", style="Field.TLabel").grid(row=r, column=0, sticky="e", pady=4, padx=(0, 8))
        row_file = ttk.Frame(form); row_file.grid(row=r, column=1, sticky="w")
        self.ent_doc_path = ttk.Entry(row_file, textvariable=self.var_doc_voo_path, width=28); self.ent_doc_path.pack(side="left")
        ttk.Button(row_file, text="Selecionar…", command=self.on_pick_file).pack(side="left", padx=6)
        ttk.Button(row_file, text="Abrir", command=self.on_open_file).pack(side="left")

        r += 1
        btns = ttk.Frame(form); btns.grid(row=r, column=0, columnspan=3, pady=(12, 0))
        ttk.Button(btns, text="Novo / Salvar", command=self.on_save).pack(side="left", padx=(0, 8))
        ttk.Button(btns, text="Limpar", command=self.on_clear_form).pack(side="left", padx=(0, 8))
        ttk.Button(btns, text="Excluir selecionado", command=self.on_delete).pack(side="left")

        form.grid_columnconfigure(1, weight=1)

        # ---- Tabela dentro do box fixo + scrollbars ----
        cols = ("id","nome","nascimento","compra","ida","volta","doc","venda","pago","lucro")
        self.tree = ttk.Treeview(table_frame, columns=cols, show="headings", selectmode="browse")
        inner_w = self.TABLE_W - 20
        inner_h = self.TABLE_H - 40
        self.tree.place(x=0, y=0, width=inner_w, height=inner_h)

        vsb = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(table_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        vsb.place(x=inner_w, y=0, height=inner_h)
        hsb.place(x=0, y=inner_h, width=inner_w)

        self.tree.tag_configure("odd", background=self.colors["row_odd"])
        self.tree.tag_configure("even", background=self.colors["row_even"])

        self._headings = {
            "id": "ID", "nome": "Nome", "nascimento": "Nascimento", "compra": "Compra",
            "ida": "Ida", "volta": "Volta", "doc": "Documento", "venda": "Venda",
            "pago": "Pago", "lucro": "Lucro",
        }
        anchors = {
            "id": "center", "nome": "w", "nascimento": "center", "compra": "center", "ida": "center",
            "volta": "center", "doc": "center", "venda": "e", "pago": "e", "lucro": "e",
        }
        default_widths = {"id":60,"nome":260,"nascimento":110,"compra":110,"ida":110,"volta":110,"doc":200,"venda":110,"pago":110,"lucro":110}

        for c in cols:
            self.tree.heading(c, text=self._headings[c], command=lambda col=c: self.sort_by(col))
            self.tree.column(c, width=default_widths[c], anchor=anchors[c], stretch=False)

        self.tree.bind("<<TreeviewSelect>>", self.on_row_select)

        # Rodapé
        footer = ttk.Frame(self.root, padding=(12, 8))
        footer.pack(side="bottom", fill="x")
        ttk.Button(footer, text="Exportar CSV (lista atual)", command=self.on_export_csv).pack(side="left")
        self.conn_badge = ttk.Label(footer, text="Conectado", style="Status.TLabel"); self.conn_badge.pack(side="left", padx=(12, 0))
        self.status = ttk.Label(footer, text=f"Banco: {DB_PATH}", style="Status.TLabel"); self.status.pack(side="right")

        # Placeholders
        self._add_placeholder(self.ent_nascimento, self.var_nascimento, "DD/MM/AAAA")
        self._add_placeholder(self.ent_compra, self.var_compra, "DD/MM/AAAA")
        self._add_placeholder(self.ent_ida, self.var_data_ida, "DD/MM/AAAA")
        self._add_placeholder(self.ent_volta, self.var_data_volta, "DD/MM/AAAA (opcional)")
        self._add_placeholder(self.ent_doc_valor, self.var_doc_valor, "Somente números p/ CPF")
        self._add_placeholder(self.ent_venda, self.var_valor_venda, "R$ 0,00")
        self._add_placeholder(self.ent_pago, self.var_valor_pago, "R$ 0,00")
        self._add_placeholder(self.ent_lucro, self.var_valor_lucro, "R$ 0,00")
        self._add_placeholder(self.ent_doc_path, self.var_doc_voo_path, "caminho/arquivo.pdf")

        # Validação de comprimento e caracteres permitidos nas datas
        vcmd_date = (self.root.register(self._validate_date_len), "%P", "%W")
        for entry in (self.ent_nascimento, self.ent_compra, self.ent_ida, self.ent_volta):
            entry.configure(validate="key", validatecommand=vcmd_date)

        # Máscara de data (insere '/' automaticamente ao digitar/colar)=
        for entry, var in (
            (self.ent_nascimento, self.var_nascimento),
            (self.ent_compra, self.var_compra),
            (self.ent_ida, self.var_data_ida),
            (self.ent_volta, self.var_data_volta),
        ):
            entry.bind("<KeyRelease>", lambda e, w=entry, v=var: self._format_date_entry(w, v))
            entry.bind("<<Paste>>",     lambda e, w=entry, v=var: self.root.after(1, lambda: self._format_date_entry(w, v)))

        # Máscara de CPF quando tipo = CPF
        self.ent_doc_valor.bind("<KeyRelease>", lambda e: self._format_cpf_entry(self.ent_doc_valor, self.var_doc_valor))
        self.ent_doc_valor.bind("<<Paste>>",     lambda e: self.root.after(1, lambda: self._format_cpf_entry(self.ent_doc_valor, self.var_doc_valor)))
        self.var_doc_tipo.trace_add("write", lambda *_: self._on_doc_tipo_changed())

    # ---------- Menu Banco ----------
    def on_change_db(self) -> None:
        from db import DB_PATH as _DB_PATH
        new_path = filedialog.asksaveasfilename(
            title="Selecionar/definir arquivo do banco de dados",
            defaultextension=".db",
            filetypes=[("SQLite DB", "*.db"), ("SQLite", "*.sqlite"), ("Todos", "*.*")],
            initialfile=os.path.basename(_DB_PATH) if _DB_PATH else "agencia_viagens.db",
        )
        if not new_path:
            return
        import db as _db
        _db.DB_PATH = new_path
        try:
            init_db()
            self.status["text"] = f"Banco: {new_path}"
            self.refresh_year_month_options()
            self.refresh_table()
            self.update_totals()
            messagebox.showinfo("Banco", "Banco de dados trocado com sucesso.")
        except Exception as exc:
            messagebox.showerror("Erro ao trocar banco", str(exc))

    def on_show_db_path(self) -> None:
        from db import DB_PATH as _DB_PATH
        messagebox.showinfo("Banco de dados", f"Caminho atual do banco:\n{_DB_PATH}")

    # ---------- Ações ----------
    def on_pick_file(self) -> None:
        path = filedialog.askopenfilename(title="Selecionar documento do voo")
        if path:
            self.var_doc_voo_path.set(path)

    def on_open_file(self) -> None:
        path = self.var_doc_voo_path.get().strip()
        if not path:
            messagebox.showinfo("Abrir arquivo", "Nenhum arquivo definido.")
            return
        import os
        if not os.path.exists(path):
            messagebox.showerror("Abrir arquivo", "Arquivo não encontrado no caminho salvo.")
            return
        try:
            if sys.platform.startswith("darwin"):
                subprocess.call(["open", path])
            elif os.name == "nt":
                os.startfile(path)  # type: ignore[attr-defined]
            else:
                subprocess.call(["xdg-open", path])
        except Exception as exc:
            messagebox.showerror("Abrir arquivo", str(exc))

    def on_apply_search(self) -> None:
        self.refresh_table()
        self.update_totals()

    def on_clear_search(self) -> None:
        self.var_busca.set("")
        self.refresh_table()
        self.update_totals()

    def on_row_select(self, _event=None) -> None:
        sel = self.tree.selection()
        if not sel:
            return
        item = self.tree.item(sel[0])
        (cid, nome, nasc, comp, ida, volta, doc, venda, pago, lucro) = item["values"]
        self.var_id.set(int(cid))
        self.var_nome.set(nome)
        self.var_nascimento.set(nasc)
        self.var_compra.set(comp)
        self.var_data_ida.set(ida)
        self.var_data_volta.set(volta)
        if ":" in doc:
            tipo, valor = doc.split(":", 1)
            self.var_doc_tipo.set(tipo.strip())
            self.var_doc_valor.set(valor.strip())
        else:
            self.var_doc_valor.set(doc)
        self.var_valor_venda.set(venda)
        self.var_valor_pago.set(pago)
        self.var_valor_lucro.set(lucro)
        self._lucro_user_edited = True

    def on_clear_form(self) -> None:
        self.var_id.set(0)
        for v in [self.var_nome, self.var_nascimento, self.var_compra, self.var_data_ida, self.var_data_volta,
                  self.var_doc_valor, self.var_valor_venda, self.var_valor_pago, self.var_valor_lucro, self.var_doc_voo_path]:
            v.set("")
        self.var_doc_tipo.set("CPF")
        self.tree.selection_remove(self.tree.selection())
        self._lucro_user_edited = False

    def on_delete(self) -> None:
        cid = self.var_id.get()
        if cid <= 0:
            messagebox.showinfo("Excluir", "Selecione um cliente na lista para excluir.")
            return
        if not messagebox.askyesno("Confirmar exclusão", f"Deseja excluir o cliente ID {cid}?"):
            return
        delete_cliente(cid)
        self.on_clear_form()
        self.refresh_table()
        self.update_totals()
        self.status["text"] = f"Cliente ID {cid} excluído."

    def compute_lucro_cents_ui(self, venda_str: str, pago_str: Optional[str]) -> Optional[int]:
        """Lucro = (valor pago pelo cliente) − (valor de venda/custo).
        O cálculo é centralizado em utils.compute_lucro_cents_from_strings.
        """
        from utils import compute_lucro_cents_from_strings
        return compute_lucro_cents_from_strings(venda_str, pago_str)
    def on_save(self) -> None:
        if not self._lucro_user_edited:
            cents = self.compute_lucro_cents_ui(self.var_valor_venda.get(), self.var_valor_pago.get())
            if cents is not None:
                self.var_valor_lucro.set(format_cents_br(cents))
        try:
            data = self._collect_and_validate_form()
        except ValueError as exc:
            messagebox.showerror("Erro de validação", str(exc))
            return
        cid = self.var_id.get()
        if cid > 0:
            update_cliente(cid, data)
            self.status["text"] = f"Cliente ID {cid} atualizado com sucesso."
        else:
            new_id = insert_cliente(data)
            self.var_id.set(new_id)
            self.status["text"] = f"Cliente criado com ID {new_id}."
        self.refresh_year_month_options()
        self.refresh_table()
        self.update_totals()

    def on_export_csv(self) -> None:
        import csv, os
        rows = [self.tree.item(i)["values"] for i in self.tree.get_children("")]
        if not rows:
            messagebox.showinfo("Exportar CSV", "Não há dados para exportar.")
            return
        fpath = filedialog.asksaveasfilename(title="Salvar como", defaultextension=".csv",
                                             filetypes=[("CSV", "*.csv"), ("Todos", "*.*")], initialfile="clientes.csv")
        if not fpath:
            return
        try:
            with open(fpath, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f, delimiter=";")
                writer.writerow(["ID","Nome","Nascimento","Compra","Ida","Volta","Documento","Venda","Pago","Lucro"])
                for r in rows:
                    writer.writerow(r)
            self.status["text"] = f"Exportado para {os.path.basename(fpath)}."
        except Exception as exc:
            messagebox.showerror("Erro ao exportar", str(exc))

    # ---------- Eventos de preço/lucro ----------
    def on_price_change(self, _event=None) -> None:
        if self._lucro_user_edited:
            return
        cents = self.compute_lucro_cents_ui(self.var_valor_venda.get(), self.var_valor_pago.get())
        if cents is not None:
            self.var_valor_lucro.set(format_cents_br(cents))

    def on_lucro_edited(self, _event=None) -> None:
        self._lucro_user_edited = True

    def on_recalc_lucro(self) -> None:
        self._lucro_user_edited = False
        self.on_price_change()

    def on_change_lucro_mode(self) -> None:
        """Recalcula lucro no modo atual se o usuário não estiver editando manualmente."""
        if not self._lucro_user_edited:
            self.on_price_change()

    # ---------- Dados / Tabela ----------
    def refresh_table(self) -> None:
        for iid in self.tree.get_children(""):
            self.tree.delete(iid)
        search = self.var_busca.get().strip()
        data = list_clientes(search)
        for idx, (cid, nome, nasc_iso, comp_iso, doc_tipo, doc_valor, venda_c, lucro_c, pago_c, ida_iso, volta_iso, _path) in enumerate(data):
            nasc = iso_to_br(nasc_iso)
            comp = iso_to_br(comp_iso)
            ida = iso_to_br(ida_iso)
            volta = iso_to_br(volta_iso) if volta_iso else ""
            doc = f"{doc_tipo}: {doc_valor}"
            venda = format_cents_br(venda_c)
            lucro = format_cents_br(lucro_c)
            pago = format_cents_br(pago_c)
            tag = "odd" if idx % 2 == 0 else "even"
            self.tree.insert("", END, values=(cid, nome, nasc, comp, ida, volta, doc, venda, pago, lucro), tags=(tag,))
        self._auto_adjust_all_columns(self.tree)

    def sort_by(self, col: str) -> None:
        rows = [self.tree.item(i)["values"] for i in self.tree.get_children("")]
        if not rows:
            return
        asc = self.col_sort_state.get(col, True)

        def to_date_br(s: str) -> datetime:
            return datetime.strptime(s, "%d/%m/%Y") if s else datetime.min

        def money_to_cents(s: str) -> int:
            try:
                return parse_currency_to_cents(s)
            except Exception:
                return 0

        key_funcs = {
            "id": lambda r: int(r[0]),
            "nome": lambda r: str(r[1]).lower(),
            "nascimento": lambda r: to_date_br(r[2]),
            "compra": lambda r: to_date_br(r[3]),
            "ida": lambda r: to_date_br(r[4]),
            "volta": lambda r: to_date_br(r[5]),
            "doc": lambda r: str(r[6]).lower(),
            "venda": lambda r: money_to_cents(r[7]),
            "pago": lambda r: money_to_cents(r[8]),
            "lucro": lambda r: money_to_cents(r[9]),
        }

        rows.sort(key=key_funcs[col], reverse=not asc)
        self.col_sort_state[col] = not asc

        for c in self._headings:
            base = self._headings[c]
            suffix = " ▲" if (c == col and not asc) else (" ▼" if (c == col and asc) else "")
            self.tree.heading(c, text=f"{base}{suffix}", command=lambda col=c: self.sort_by(col))

        for iid in self.tree.get_children(""):
            self.tree.delete(iid)
        for r in rows:
            self.tree.insert("", END, values=r)

        self._auto_adjust_all_columns(self.tree)

    # ---------- Totais ----------
    def refresh_year_month_options(self) -> None:
        years = available_years()
        cur = self.var_ano.get()
        year_vals = [str(y) for y in years]
        if cur and cur not in year_vals:
            year_vals.append(cur)
        self.cmb_ano["values"] = year_vals
        if not cur and year_vals:
            self.var_ano.set(str(years[-1]))

    def update_totals(self) -> None:
        mes_map = {"Janeiro":1,"Fevereiro":2,"Março":3,"Abril":4,"Maio":5,"Junho":6,"Julho":7,"Agosto":8,"Setembro":9,"Outubro":10,"Novembro":11,"Dezembro":12}
        try:
            year = int(self.var_ano.get()) if self.var_ano.get() else None
        except ValueError:
            year = None
        mes_nome = self.var_mes.get()
        month = mes_map.get(mes_nome) if mes_nome and mes_nome != "Todos" else None
        lucro_mes = sum_lucro(year=year, month=month) if month else 0
        lucro_ano = sum_lucro(year=year) if year else sum_lucro()
        self.lbl_total_mes.configure(text=(f"Total (Mês): {format_cents_br(lucro_mes)}" if month else "Total (Mês): —"))
        self.lbl_total_ano.configure(text=f"Total (Ano): {format_cents_br(lucro_ano)}")

    # ---------- Coleta/Validação ----------
    def _collect_and_validate_form(self) -> Dict[str, object]:
        nome = self.var_nome.get().strip()
        nasc = self.var_nascimento.get().strip()
        compra = self.var_compra.get().strip()
        ida = self.var_data_ida.get().strip()
        volta = self.var_data_volta.get().strip()
        doc_tipo = self.var_doc_tipo.get().strip()
        doc_valor = self.var_doc_valor.get().strip()
        venda_str = self.var_valor_venda.get().strip()
        pago_str = self.var_valor_pago.get().strip()
        lucro_str = self.var_valor_lucro.get().strip()
        doc_path = self.var_doc_voo_path.get().strip()

        placeholders = {"DD/MM/AAAA","DD/MM/AAAA (opcional)","Somente números p/ CPF","R$ 0,00","caminho/arquivo.pdf"}
        if nasc in placeholders: nasc = ""
        if compra in placeholders: compra = ""
        if ida in placeholders: ida = ""
        if volta in placeholders: volta = ""
        if doc_valor in placeholders: doc_valor = ""
        if venda_str in placeholders: venda_str = ""
        if pago_str in placeholders: pago_str = ""
        if lucro_str in placeholders: lucro_str = ""
        if doc_path in placeholders: doc_path = ""

        if not nome: raise ValueError("Informe o Nome completo.")
        if not nasc: raise ValueError("Informe a Data de nascimento.")
        if not compra: raise ValueError("Informe a Data de compra do voo.")
        if not ida: raise ValueError("Informe a Data de ida.")
        if doc_tipo not in ("CPF", "Passaporte"): raise ValueError("Selecione o tipo de documento (CPF ou Passaporte).")
        if not doc_valor: raise ValueError("Informe o número do documento.")
        if not venda_str: raise ValueError("Informe o Valor de compra.")
        if not lucro_str:
            cents = self.compute_lucro_cents_ui(venda_str, pago_str)
            if cents is not None:
                lucro_str = format_cents_br(cents)
                self.var_valor_lucro.set(lucro_str)
            if not lucro_str:
                raise ValueError("Informe o Valor lucrado.")

        try: nasc_iso = br_to_iso(nasc)
        except ValueError: raise ValueError("Data de nascimento inválida. Use DD/MM/AAAA.") from None
        try: compra_iso = br_to_iso(compra)
        except ValueError: raise ValueError("Data de compra do voo inválida. Use DD/MM/AAAA.") from None
        try: ida_iso = br_to_iso(ida)
        except ValueError: raise ValueError("Data de ida inválida. Use DD/MM/AAAA.") from None

        volta_iso = None
        if volta:
            try: volta_iso = br_to_iso(volta)
            except ValueError: raise ValueError("Data de volta inválida. Use DD/MM/AAAA.") from None

        if doc_tipo == "CPF" and not valido_cpf(doc_valor):
            raise ValueError("CPF inválido. Verifique os dígitos (11 números).")

        try: venda_cents = parse_currency_to_cents(venda_str)
        except ValueError: raise ValueError("Valor de compra inválido.") from None
        try: pago_cents = parse_currency_to_cents(pago_str)
        except ValueError: raise ValueError("Valor pago inválido.") from None
        try: lucro_cents = parse_currency_to_cents(lucro_str)
        except ValueError: raise ValueError("Valor lucrado inválido.") from None

        # Venda não pode ser negativa; Pago e Lucro podem.
        if venda_cents < 0:
            raise ValueError("Valor de compra não pode ser negativo. 'Valor pago' e 'Lucro' podem ser negativos.")

        return {
            "nome_completo": nome,
            "data_nascimento": nasc_iso,
            "data_compra_voo": compra_iso,
            "doc_tipo": doc_tipo,
            "doc_valor": somente_digitos(doc_valor) if doc_tipo == "CPF" else doc_valor.strip(),
            "valor_venda_cents": venda_cents,
            "valor_lucro_cents": lucro_cents,
            "valor_pago_cents": pago_cents,
            "data_ida": ida_iso,
            "data_volta": volta_iso,
            "doc_voo_path": doc_path or None,
        }

    # ---------- Vendas por Mês/Ano ----------
    def open_month_year_view(self) -> None:
        win = Toplevel(self.root); win.title("Vendas por Mês/Ano"); win.geometry("1200x720")
        top = ttk.Frame(win, padding=(12, 10)); top.pack(side="top", fill="x")

        ttk.Label(top, text="Ano:", style="Field.TLabel").grid(row=0, column=0, padx=(0, 6), sticky="e")
        years = [str(y) for y in available_years()]
        var_ano2 = StringVar(value=years[-1] if years else str(datetime.now().year))
        cmb_ano2 = ttk.Combobox(top, textvariable=var_ano2, values=years, width=8, state="readonly"); cmb_ano2.grid(row=0, column=1, sticky="w")

        ttk.Label(top, text="Mês:", style="Field.TLabel").grid(row=0, column=2, padx=(12, 6), sticky="e")
        meses = ["Todos","Janeiro","Fevereiro","Março","Abril","Maio","Junho","Julho","Agosto","Setembro","Outubro","Novembro","Dezembro"]
        var_mes2 = StringVar(value="Todos")
        cmb_mes2 = ttk.Combobox(top, textvariable=var_mes2, values=meses, width=12, state="readonly"); cmb_mes2.grid(row=0, column=3, sticky="w")

        btn_aplicar = ttk.Button(top, text="Aplicar Filtro", command=lambda: populate()); btn_aplicar.grid(row=0, column=4, padx=(12, 0))
        lbl_tot = ttk.Label(top, text="Total (Lucro): R$ 0,00", style="Header.TLabel"); lbl_tot.grid(row=0, column=5, padx=(18, 0))

        container = ttk.Frame(win); container.pack(fill="both", expand=True, padx=12, pady=8)
        table = ttk.Treeview(container, columns=("id","nome","ida","volta","compra","doc","venda","pago","lucro"), show="headings")
        vsb = ttk.Scrollbar(container, orient="vertical", command=table.yview)
        hsb = ttk.Scrollbar(container, orient="horizontal", command=table.xview)
        table.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        table.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        container.grid_rowconfigure(0, weight=1)
        container.grid_columnconfigure(0, weight=1)

        cfg = {
            "id": (60, "center", "ID"),
            "nome": (300, "w", "Nome"),
            "ida": (120, "center", "Ida"),
            "volta": (120, "center", "Volta"),
            "compra": (120, "center", "Compra"),
            "doc": (220, "center", "Documento"),
            "venda": (120, "e", "Venda"),
            "pago": (120, "e", "Pago"),
            "lucro": (120, "e", "Lucro"),
        }
        for c, (w, anc, t) in cfg.items():
            table.heading(c, text=t)
            table.column(c, width=w, anchor=anc, stretch=False)

        def export_csv_local() -> None:
            import csv, os
            rows_local = [table.item(i)["values"] for i in table.get_children("")]
            if not rows_local:
                messagebox.showinfo("Exportar CSV", "Não há dados para exportar.")
                return
            fpath = filedialog.asksaveasfilename(
                title="Salvar como", defaultextension=".csv",
                filetypes=[("CSV", "*.csv")], initialfile="vendas_mes_ano.csv"
            )
            if not fpath: return
            with open(fpath, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f, delimiter=";")
                writer.writerow(["ID","Nome","Ida","Volta","Compra","Documento","Venda","Pago","Lucro"])
                for r in rows_local: writer.writerow(r)
            messagebox.showinfo("Exportar CSV", f"Exportado para {os.path.basename(fpath)}.")

        ttk.Button(win, text="Exportar CSV (filtro)", command=export_csv_local).pack(side="bottom", anchor="w", padx=12, pady=(0, 10))

        mes_map = {"Janeiro":1,"Fevereiro":2,"Março":3,"Abril":4,"Maio":5,"Junho":6,"Julho":7,"Agosto":8,"Setembro":9,"Outubro":10,"Novembro":11,"Dezembro":12}

        def populate() -> None:
            for iid in table.get_children(""):
                table.delete(iid)
            try:
                y = int(var_ano2.get())
            except ValueError:
                messagebox.showerror("Ano inválido", "Selecione um ano válido.")
                return
            mn = var_mes2.get()
            m = mes_map.get(mn) if mn != "Todos" else None
            rows_local = list_by_month_year(y, m)
            total_lucro = 0
            for (cid, nome, _nasc_iso, comp_iso, doc_tipo, doc_valor, venda_c, lucro_c, pago_c, ida_iso, volta_iso, _path) in rows_local:
                table.insert("", END, values=(
                    cid, nome, iso_to_br(ida_iso), iso_to_br(volta_iso) if volta_iso else "",
                    iso_to_br(comp_iso), f"{doc_tipo}: {doc_valor}",
                    format_cents_br(venda_c), format_cents_br(pago_c), format_cents_br(lucro_c)
                ))
                total_lucro += int(lucro_c)
            lbl_tot["text"] = f"Total (Lucro): {format_cents_br(total_lucro)}"
            for col in table["columns"]:
                self._auto_adjust_column(table, col)

        populate()

    # ---------- Alertas de Voo ----------
    def check_upcoming_flights(self, show_if_empty: bool = False) -> None:
        tomorrow = date.today() + timedelta(days=1)
        rows = flights_departing_on(tomorrow)
        if rows:
            linhas = [self._build_flight_line(*r) for r in rows]
            if show_if_empty:
                messagebox.showinfo("Voos de amanhã", f"Encontramos {len(rows)} voo(s) com ida amanhã:\n\n" + "\n\n".join(linhas))
            else:
                self.show_toast(f"{len(rows)} voo(s) com ida amanhã.")
        elif show_if_empty:
            messagebox.showinfo("Voos de amanhã", "Nenhum voo com ida amanhã.")

    def _build_flight_line(self, cid: int, nome: str, ida_iso: str, volta_iso: Optional[str], doc_tipo: str, doc_valor: str, path: Optional[str]) -> str:
        ida_br = iso_to_br(ida_iso)
        volta_br = iso_to_br(volta_iso) if volta_iso else "—"
        tem_doc = "Sim" if path else "Não"
        return (f"ID {cid} — {nome}\n"
                f"Ida: {ida_br} | Volta: {volta_br} | {doc_tipo}: {doc_valor}\n"
                f"Documento salvo: {tem_doc}")

    def schedule_hourly_check(self) -> None:
        self.root.after(60 * 60 * 1000, lambda: (self.check_upcoming_flights(show_if_empty=False), self.schedule_hourly_check()))

    # ---------- Validação de entrada p/ datas ----------
    def _validate_date_len(self, proposed: str, widget_name: str) -> bool:
        """
        Permite apenas dígitos e '/', máximo 10 chars (DD/MM/AAAA),
        e no máximo 8 dígitos. Aceita vazio e placeholders (com letras).
        """
        val = proposed or ""
        if any(ch.isalpha() for ch in val):
            return True
        if val == "":
            return True
        for ch in val:
            if not (ch.isdigit() or ch == "/"):
                return False
        if len(val) > 10:
            return False
        if sum(ch.isdigit() for ch in val) > 8:
            return False
        return True

    # ---------- Máscaras com gerenciamento de cursor ----------
    def _format_date_entry(self, entry: tk.Entry, var: StringVar) -> None:
        """Formata como DD/MM/AAAA enquanto digita/cola, preservando o cursor."""
        if self._masking_guard:
            return
        val = var.get() or ""
        if any(ch.isalpha() for ch in val):
            return
        try:
            self._masking_guard = True
            pos = entry.index("insert")
            digits_left = sum(ch.isdigit() for ch in val[:pos])
            digits = "".join(ch for ch in val if ch.isdigit())[:8]

            out = ""
            map_digit_to_disp = []
            for i, d in enumerate(digits):
                if i in (2, 4):
                    out += "/"
                disp_index = len(out)
                out += d
                map_digit_to_disp.append(disp_index)

            if out != val:
                var.set(out)

            if digits_left <= 0:
                new_pos = 0
            elif digits_left > len(map_digit_to_disp):
                new_pos = len(out)
            else:
                new_pos = map_digit_to_disp[digits_left - 1] + 1
            entry.icursor(new_pos)
        finally:
            self._masking_guard = False

    def _format_cpf_entry(self, entry: tk.Entry, var: StringVar) -> None:
        """Formata CPF (000.000.000-00) quando o tipo = CPF, preservando o cursor."""
        if self._masking_guard:
            return
        if (self.var_doc_tipo.get() or "").strip().upper() != "CPF":
            return
        val = var.get() or ""
        if any(ch.isalpha() for ch in val):
            return
        try:
            self._masking_guard = True
            pos = entry.index("insert")
            digits_left = sum(ch.isdigit() for ch in val[:pos])
            digits = "".join(ch for ch in val if ch.isdigit())[:11]

            out = ""
            map_digit_to_disp = []
            for i, d in enumerate(digits):
                if i in (3, 6):
                    out += "."
                if i == 9:
                    out += "-"
                disp_index = len(out)
                out += d
                map_digit_to_disp.append(disp_index)

            if out != val:
                var.set(out)

            if digits_left <= 0:
                new_pos = 0
            elif digits_left > len(map_digit_to_disp):
                new_pos = len(out)
            else:
                new_pos = map_digit_to_disp[digits_left - 1] + 1
            entry.icursor(new_pos)
        finally:
            self._masking_guard = False

    def _on_doc_tipo_changed(self) -> None:
        if (self.var_doc_tipo.get() or "").strip().upper() == "CPF" and hasattr(self, "ent_doc_valor"):
            self._format_cpf_entry(self.ent_doc_valor, self.var_doc_valor)

    # ---------- UI Utils ----------
    def _attach_tooltip(self, widget, text: str) -> None:
        tip = None
        def enter(_e):
            nonlocal tip
            if tip: return
            tip = Toplevel(widget); tip.wm_overrideredirect(True); tip.attributes("-topmost", True)
            x = widget.winfo_rootx() + 10; y = widget.winfo_rooty() + widget.winfo_height() + 6
            tip.geometry(f"+{x}+{y}")
            lbl = ttk.Label(tip, text=text, style="Status.TLabel", padding=(6, 4)); lbl.pack()
        def leave(_e):
            nonlocal tip
            if tip: tip.destroy(); tip = None
        widget.bind("<Enter>", enter); widget.bind("<Leave>", leave)

    def show_toast(self, text: str, duration_ms: int = 4000) -> None:
        toast = Toplevel(self.root); toast.wm_overrideredirect(True); toast.attributes("-topmost", True)
        self.root.update_idletasks()
        x = self.root.winfo_rootx() + self.root.winfo_width() - 320
        y = self.root.winfo_rooty() + self.root.winfo_height() - 80
        toast.geometry(f"300x50+{x}+{y}")
        ttk.Label(toast, text=text, style="Status.TLabel", padding=(10, 8)).pack(fill="both", expand=True)
        toast.after(duration_ms, toast.destroy)

    def _add_placeholder(self, entry, var: StringVar, placeholder: str) -> None:
        def on_focus_in(_e):
            if var.get() == placeholder: var.set("")
        def on_focus_out(_e):
            if not var.get().strip(): var.set(placeholder)
        if not var.get(): var.set(placeholder)
        entry.bind("<FocusIn>", on_focus_in)
        entry.bind("<FocusOut>", on_focus_out)


def main() -> None:
    init_db()
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
