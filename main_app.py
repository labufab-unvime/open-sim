#!/usr/bin/env python3
"""
MICROFLUIDIC NETWORK SIMULATOR - VERSIÓN MODULAR 6.2
- [FIX v6.2] CORREGIDO EL BUG DE ACTUALIZACIÓN DE PARÁMETROS.
  'Run Simulation' NO estaba re-leyendo los valores de Viscosidad
  o Altura del canal de la UI. Usaba los valores 'cacheados' de
  cuando 'Build Network' fue presionado.
- [FIX] 'run_simulation' ahora lee Viscosity y Height CADA VEZ,
  y recalcula las resistencias de la red (edge['R']) antes de
  llamar al solver.
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import logging
import datetime
import math
import csv

# Importar los nuevos módulos
from svg_parser import SVGMicrofluidicParser
from network_builder import NetworkBuilder
from physics_solver import solve_network_poiseuille
from visualization import visualize_elements, visualize_network, visualize_results

# Importar el tema estético
try:
    import sv_ttk
except ImportError:
    print("---------------------------------------------------------------")
    print("AVISO: Paquete de tema no encontrado.")
    print("Para la estética de Flui3d, por favor instala: pip install sv-ttk")
    print("---------------------------------------------------------------")

# Configurar logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class IntegratedMicrofluidicApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Microfluidic Network Simulator - Modular v6.2")
        self.root.geometry("1400x1000")

        # Aplicar tema estético "light"
        try:
            sv_ttk.set_theme("light")
            plt.style.use('default') # Usar el estilo por defecto (blanco)
            self.theme_bg = "#FFFFFF" # Fondo blanco para el texto
        except Exception as e:
            print(f"No se pudo aplicar el tema sv_ttk. Usando tema por defecto. Error: {e}")
            self.theme_bg = 'SystemButtonFace' # Fallback

        self.parser = SVGMicrofluidicParser()
        self.builder = NetworkBuilder()
        self.current_file = None
        self.simulation_results = None

        # Para selección manual
        self.selected_inlets = []
        self.selected_outlets = []
        self.selected_channels = []
        self.selected_cameras = []
        self.selection_mode = None
        self.hidden_elements = []

        # Para zoom y pan
        self.pan_start = None
        self.dragging = False
        self.pan_ax = None

        self.colorbar = None # La barra de color ahora es manejada por visualization.py

        # Opciones de ploteo
        self.plot_mode = tk.StringVar(value="pressure")
        self.pressure_cmap = tk.StringVar(value='Reds')
        self.pressure_scale = tk.StringVar(value='log')
        self.flow_cmap = tk.StringVar(value='Blues')
        self.flow_scale = tk.StringVar(value='linear')
        self.colormaps_list = plt.colormaps()

        # Variables de estado de zoom/pan
        self.last_plot_xlim = None
        self.last_plot_ylim = None
        self.last_plot_aspect = 'equal' # Estado inicial

        self.setup_ui()

    def setup_ui(self):
        # Create notebook for tabs
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Tab 1: SVG Visualization
        self.viz_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.viz_frame, text="SVG Visualization")
        # Tab 2: Network Configuration
        self.network_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.network_frame, text="Network Configuration")
        # Tab 3: Simulation Results
        self.results_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.results_frame, text="Simulation Results")
        # Tab 4: About
        self.about_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.about_frame, text="About")

        self.setup_visualization_tab()
        self.setup_network_tab()
        self.setup_results_tab()
        self.setup_about_tab()

    def setup_visualization_tab(self):
        # Fila 1: Controles de Archivo y Vista
        control_frame_top = ttk.Frame(self.viz_frame)
        control_frame_top.pack(fill=tk.X, pady=2)
        ttk.Button(control_frame_top, text="Load SVG", command=self.load_svg).pack(side=tk.LEFT, padx=5)
        ttk.Button(control_frame_top, text="Refresh View", command=self.refresh_view).pack(side=tk.LEFT, padx=5)
        ttk.Button(control_frame_top, text="Show All Hidden", command=self.reset_hidden_elements).pack(side=tk.LEFT, padx=5)
        ttk.Button(control_frame_top, text="Clear", command=self.clear_view).pack(side=tk.LEFT, padx=5)
        ttk.Button(control_frame_top, text="Reset Zoom", command=self.reset_zoom).pack(side=tk.LEFT, padx=5)

        # Fila 2: Herramientas de Selección (Componentes Actuales)
        control_frame_bottom = ttk.Frame(self.viz_frame)
        control_frame_bottom.pack(fill=tk.X, pady=2)
        ttk.Button(control_frame_bottom, text="Select Inlet", command=lambda: self.set_selection_mode('inlet')).pack(side=tk.LEFT, padx=5)
        ttk.Button(control_frame_bottom, text="Select Outlet", command=lambda: self.set_selection_mode('outlet')).pack(side=tk.LEFT, padx=5)
        ttk.Button(control_frame_bottom, text="Select Channel", command=lambda: self.set_selection_mode('channel')).pack(side=tk.LEFT, padx=5)
        ttk.Button(control_frame_bottom, text="Select Chamber", command=lambda: self.set_selection_mode('camera')).pack(side=tk.LEFT, padx=5)

        # Fila 3: Herramientas de Selección (Futuros Componentes)
        control_frame_future = ttk.Frame(self.viz_frame)
        control_frame_future.pack(fill=tk.X, pady=(2, 5))
        f1 = ttk.Button(control_frame_future, text="Select Serpentine", command=lambda: self.set_selection_mode('serpentine'), state=tk.DISABLED)
        f1.pack(side=tk.LEFT, padx=5)
        f2 = ttk.Button(control_frame_future, text="Select Filter", command=lambda: self.set_selection_mode('filter'), state=tk.DISABLED)
        f2.pack(side=tk.LEFT, padx=5)
        f3 = ttk.Button(control_frame_future, text="Select Tesla Valve", command=lambda: self.set_selection_mode('tesla'), state=tk.DISABLED)
        f3.pack(side=tk.LEFT, padx=5)
        f4 = ttk.Button(control_frame_future, text="Select Transition", command=lambda: self.set_selection_mode('transition'), state=tk.DISABLED)
        f4.pack(side=tk.LEFT, padx=5)
        ttk.Button(control_frame_future, text="Hide Element", command=lambda: self.set_selection_mode('hide')).pack(side=tk.LEFT, padx=5)
        ttk.Button(control_frame_future, text="Clear Selection", command=self.clear_selection).pack(side=tk.LEFT, padx=5)
        self.selection_label = ttk.Label(control_frame_future, text="Selection: None")
        self.selection_label.pack(side=tk.LEFT, padx=10)

        # Create matplotlib figure
        self.fig, self.ax = plt.subplots(figsize=(12, 8))
        self.canvas = FigureCanvasTkAgg(self.fig, master=self.viz_frame)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True, pady=5)
        self.canvas.mpl_connect('button_press_event', self.on_click)
        self.canvas.mpl_connect('scroll_event', self.on_scroll)
        self.canvas.mpl_connect('button_press_event', self.on_press)
        self.canvas.mpl_connect('button_release_event', self.on_release)
        self.canvas.mpl_connect('motion_notify_event', self.on_motion)

        # Elements list
        list_frame = ttk.Frame(self.viz_frame)
        list_frame.pack(fill=tk.BOTH, expand=False, pady=5)
        self.tree = ttk.Treeview(list_frame, columns=('ID', 'Type', 'Details'), show='headings', height=6)
        self.tree.heading('ID', text='Element ID'); self.tree.heading('Type', text='Type'); self.tree.heading('Details', text='Details')
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

    def setup_network_tab(self):
        main_frame = ttk.Frame(self.network_frame)
        main_frame.pack(fill=tk.BOTH, expand=True)
        left_frame = ttk.Frame(main_frame, width=400); left_frame.pack(side=tk.LEFT, fill=tk.Y, padx=10, pady=5)
        right_frame = ttk.Frame(main_frame); right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=10, pady=5)

        # Parameters frame
        params_frame = ttk.LabelFrame(left_frame, text="Simulation Parameters")
        params_frame.pack(fill=tk.X, pady=5)
        ttk.Label(params_frame, text="Viscosity (mPa·s):").grid(row=0, column=0, padx=5, pady=2, sticky=tk.W)
        self.viscosity_entry = ttk.Entry(params_frame); self.viscosity_entry.insert(0, "0.862")
        self.viscosity_entry.grid(row=0, column=1, padx=5, pady=2)
        ttk.Label(params_frame, text="Channel Height (µm):").grid(row=1, column=0, padx=5, pady=2, sticky=tk.W)
        self.height_entry = ttk.Entry(params_frame); self.height_entry.insert(0, "50")
        self.height_entry.grid(row=1, column=1, padx=5, pady=2)

        # Boundary conditions
        bc_frame = ttk.LabelFrame(left_frame, text="Boundary Conditions")
        bc_frame.pack(fill=tk.X, pady=5)
        ttk.Label(bc_frame, text="Inlet Type:").grid(row=0, column=0, padx=5, pady=2, sticky=tk.W)
        self.inlet_type = tk.StringVar(value="flow")
        ttk.Radiobutton(bc_frame, text="Flow", variable=self.inlet_type, value="flow").grid(row=0, column=1, padx=5, pady=2)
        ttk.Radiobutton(bc_frame, text="Pressure", variable=self.inlet_type, value="pressure").grid(row=0, column=2, padx=5, pady=2)
        ttk.Label(bc_frame, text="Inlet Value:").grid(row=1, column=0, padx=5, pady=2, sticky=tk.W)
        self.inlet_value_entry = ttk.Entry(bc_frame); self.inlet_value_entry.insert(0, "8")
        self.inlet_value_entry.grid(row=1, column=1, padx=5, pady=2, columnspan=2)
        ttk.Label(bc_frame, text="(µL/min or Pa)").grid(row=1, column=3, padx=5, pady=2)
        ttk.Label(bc_frame, text="Outlet Pressure (Pa):").grid(row=2, column=0, padx=5, pady=2, sticky=tk.W)
        self.outlet_pressure_entry = ttk.Entry(bc_frame); self.outlet_pressure_entry.insert(0, "0")
        self.outlet_pressure_entry.grid(row=2, column=1, padx=5, pady=2, columnspan=2)

        # Buttons
        button_frame = ttk.Frame(left_frame); button_frame.pack(fill=tk.X, pady=10)
        ttk.Button(button_frame, text="Build Network", command=self.build_network).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Run Simulation", command=self.run_simulation).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Export Results", command=self.export_results).pack(side=tk.LEFT, padx=5)

        # --- INICIO DEL FIX v5.7 ---
        # Lista de componentes de la red (para debug)
        # Movido al 'left_frame' para visibilidad.
        net_list_frame = ttk.LabelFrame(left_frame, text="Built Network Components (for Debugging)")
        # Se usa fill=BOTH y expand=True para que llene el espacio restante
        net_list_frame.pack(fill=tk.BOTH, expand=True, pady=(10,0), padx=0)

        cols = ('ID', 'Type', 'Length (µm)', 'Width (µm)', 'Resistance (Pa·s/m³)')
        self.network_tree = ttk.Treeview(net_list_frame, columns=cols, show='headings', height=6)

        col_widths = {'ID': 110, 'Type': 60, 'Length (µm)': 60, 'Width (µm)': 60, 'Resistance (Pa·s/m³)': 90}
        for col, width in col_widths.items():
            self.network_tree.heading(col, text=col)
            self.network_tree.column(col, width=width, minwidth=40, stretch=True)

        net_scrollbar = ttk.Scrollbar(net_list_frame, orient=tk.VERTICAL, command=self.network_tree.yview)
        self.network_tree.configure(yscrollcommand=net_scrollbar.set)
        self.network_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        net_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        # --- FIN DEL FIX v5.7 ---

        # Network visualization
        net_viz_frame = ttk.Frame(right_frame); net_viz_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        self.net_fig, self.net_ax = plt.subplots(figsize=(10, 6))
        self.net_canvas = FigureCanvasTkAgg(self.net_fig, master=net_viz_frame)
        self.net_canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        self.net_canvas.mpl_connect('scroll_event', self.on_scroll)
        self.net_canvas.mpl_connect('button_press_event', self.on_press)
        self.net_canvas.mpl_connect('button_release_event', self.on_release)
        self.net_canvas.mpl_connect('motion_notify_event', self.on_motion)

        # El 'net_list_frame' fue movido de aquí (v5.6) al left_frame (v5.7)


    def setup_results_tab(self):
        main_frame = ttk.Frame(self.results_frame); main_frame.pack(fill=tk.BOTH, expand=True)
        left_frame = ttk.Frame(main_frame, width=450); left_frame.pack(side=tk.LEFT, fill=tk.Y, padx=10, pady=5)
        right_frame = ttk.Frame(main_frame); right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=10, pady=5)

        # Plot selection frame
        plot_select_frame = ttk.LabelFrame(left_frame, text="Plot Options")
        plot_select_frame.pack(fill=tk.X, pady=5, padx=5)
        ttk.Label(plot_select_frame, text="Visualize:").grid(row=0, column=0, padx=5, pady=5)
        ttk.Radiobutton(plot_select_frame, text="Pressure", variable=self.plot_mode,
                        value="pressure", command=self.update_plot).grid(row=0, column=1, padx=5, pady=5)
        ttk.Radiobutton(plot_select_frame, text="Flow", variable=self.plot_mode,
                        value="flow", command=self.update_plot).grid(row=0, column=2, padx=5, pady=5)
        ttk.Button(plot_select_frame, text="Export PNG",
                   command=self.export_simulation_image).grid(row=0, column=3, padx=10, pady=5, sticky=tk.E)

        # Plot Customization Frame
        custom_frame = ttk.LabelFrame(left_frame, text="Plot Customization")
        custom_frame.pack(fill=tk.X, pady=5, padx=5)
        ttk.Label(custom_frame, text="Pressure Plot:", font="-weight bold").grid(row=0, column=0, columnspan=3, sticky=tk.W, padx=5, pady=2)
        ttk.Label(custom_frame, text="  Colormap:").grid(row=1, column=0, sticky=tk.W, padx=5)
        pressure_cmap_combo = ttk.Combobox(custom_frame, textvariable=self.pressure_cmap, values=self.colormaps_list, width=10)
        pressure_cmap_combo.grid(row=1, column=1, padx=5, pady=2, sticky=tk.W)
        pressure_cmap_combo.bind("<<ComboboxSelected>>", self.update_plot)
        ttk.Radiobutton(custom_frame, text="Log", variable=self.pressure_scale, value='log', command=self.update_plot).grid(row=1, column=2, sticky=tk.W)
        ttk.Radiobutton(custom_frame, text="Linear", variable=self.pressure_scale, value='linear', command=self.update_plot).grid(row=1, column=3, sticky=tk.W)
        ttk.Label(custom_frame, text="Flow Plot:", font="-weight bold").grid(row=2, column=0, columnspan=3, sticky=tk.W, padx=5, pady=2)
        ttk.Label(custom_frame, text="  Colormap:").grid(row=3, column=0, sticky=tk.W, padx=5)
        flow_cmap_combo = ttk.Combobox(custom_frame, textvariable=self.flow_cmap, values=self.colormaps_list, width=10)
        flow_cmap_combo.grid(row=3, column=1, padx=5, pady=2, sticky=tk.W)
        flow_cmap_combo.bind("<<ComboboxSelected>>", self.update_plot)
        ttk.Radiobutton(custom_frame, text="Log", variable=self.flow_scale, value='log', command=self.update_plot).grid(row=3, column=2, sticky=tk.W)
        ttk.Radiobutton(custom_frame, text="Linear", variable=self.flow_scale, value='linear', command=self.update_plot).grid(row=3, column=3, sticky=tk.W)

        # Results text area
        results_text_frame = ttk.LabelFrame(left_frame, text="Simulation Report")
        results_text_frame.pack(fill=tk.BOTH, expand=True, pady=5, padx=5)
        self.results_text = tk.Text(results_text_frame, height=15, width=50)
        scrollbar = ttk.Scrollbar(results_text_frame, orient=tk.VERTICAL, command=self.results_text.yview)
        self.results_text.configure(yscrollcommand=scrollbar.set)
        self.results_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Results visualization
        results_viz_frame = ttk.LabelFrame(right_frame, text="Pressure & Flow Visualization")
        results_viz_frame.pack(fill=tk.BOTH, expand=True, pady=5, padx=5)

        # --- INICIO DEL FIX v5.3 (basado en input de ChatGPT) ---
        self.results_fig, self.results_ax = plt.subplots(figsize=(10, 6))
        self.results_fig.set_tight_layout(False)  # Desactiva el auto-layout
        # Fija la posición del gráfico [left, bottom, width, height]
        self.results_ax.set_position([0.10, 0.12, 0.75, 0.80])
        # --- FIN DEL FIX v5.3 ---

        self.results_canvas = FigureCanvasTkAgg(self.results_fig, master=results_viz_frame)
        self.results_canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        self.results_canvas.mpl_connect('scroll_event', self.on_scroll)
        self.results_canvas.mpl_connect('button_press_event', self.on_press)
        self.results_canvas.mpl_connect('button_release_event', self.on_release)
        self.results_canvas.mpl_connect('motion_notify_event', self.on_motion)

    def setup_about_tab(self):
        about_text_frame = ttk.Frame(self.about_frame, padding="20")
        about_text_frame.pack(expand=True, fill=tk.BOTH)

        about_text = tk.Text(about_text_frame, height=20, width=80, wrap=tk.WORD,
                             font=("Helvetica", 11), relief=tk.FLAT, background=self.theme_bg)
        about_text.pack(expand=True, fill=tk.BOTH, padx=10, pady=10)

        # Configurar etiquetas de estilo
        about_text.tag_configure("h1", font=("Helvetica", 20, "bold"), spacing3=10)
        about_text.tag_configure("h2", font=("Helvetica", 14, "bold"), spacing3=5)
        about_text.tag_configure("body", font=("Helvetica", 11), lmargin1=10, lmargin2=10)
        about_text.tag_configure("credits", font=("Helvetica", 10, "italic"), lmargin1=10, lmargin2=10)

        # --- INICIO DEL CONTENIDO ACTUALIZADO EN INGLÉS ---

        about_text.insert(tk.END, "Microfluidic Network Simulator\n", "h1")
        about_text.insert(tk.END, f"Version: 6.2 (Modular)\n", "body")
        about_text.insert(tk.END, f"Date: {datetime.date.today().isoformat()}\n\n", "body")

        about_text.insert(tk.END, "Software Purpose\n", "h2")
        about_text.insert(tk.END,
            "This software is designed to perform fast and accessible simulations of "
            "microfluidic networks. It calculates the pressure distribution and flow rates "
            "in a device composed of channels and chambers.\n\n", "body")

        about_text.insert(tk.END, "Mathematical Model\n", "h2")
        about_text.insert(tk.END,
            "The simulation is based on a hydraulic resistance model. It uses the "
            "complete analytical solution for Hagen-Poiseuille flow in rectangular channels "
            "(based on Bruus, 2008, Eq. 2.45). This model provides high accuracy "
            "for any channel aspect ratio (width-to-height) within the laminar flow regime.\n\n", "body")

        about_text.insert(tk.END, "Intended Use & Compatibility\n", "h2")
        about_text.insert(tk.END,
            "This simulator is specifically optimized for SVG (Scalable Vector Graphics) "
            "files generated by the flui3d.org web platform. Compatibility with "
            "SVGs from other sources (e.g., Inkscape, Adobe Illustrator) is not guaranteed, "
            "as the parser expects the specific file structure from flui3d.org.\n\n", "body")

        about_text.insert(tk.END, "Credits\n", "h2")
        about_text.insert(tk.END, "Principal Developer:\n", "body")
        about_text.insert(tk.END, "  •  Lorenzo Tell\n", "credits")
        about_text.insert(tk.END, "     Advanced Bioengineering Student\n", "credits")
        about_text.insert(tk.END, "     Universidad Nacional de Villa Mercedes - LabµFab\n\n", "credits")

        about_text.insert(tk.END, "With support from:\n", "body")
        about_text.insert(tk.END, "  •  CEB (Club Estudiantil de Bioingeniería)\n\n", "credits")

        about_text.insert(tk.END, "AI Assistance & Collaborative Development:\n", "body")
        about_text.insert(tk.END, "  •  Google Gemini\n  •  OpenAI ChatGPT\n  •  DeepSeek\n\n", "credits")

        about_text.insert(tk.END, "License\n", "h2")
        about_text.insert(tk.END, "This software is provided 'as is', without warranty of any kind, "
            "express or implied. Use at your own risk. (Pending License - MIT Recommended).\n", "body")

        # --- FIN DEL CONTENIDO ACTUALIZADO ---

        about_text.config(state=tk.DISABLED)

    # ========== EVENTOS DE ZOOM Y PAN GENERALIZADOS ==========

    def on_scroll(self, event):
        ax = event.inaxes
        if not ax: return
        base_scale = 1.1
        xdata, ydata = event.xdata, event.ydata
        if xdata is None or ydata is None: return

        if event.button == 'up': scale_factor = 1 / base_scale
        elif event.button == 'down': scale_factor = base_scale
        else: return

        xlim = ax.get_xlim(); ylim = ax.get_ylim()
        new_width = (xlim[1] - xlim[0]) * scale_factor; new_height = (ylim[1] - ylim[0]) * scale_factor
        relx = (xlim[1] - xdata) / (xlim[1] - xlim[0]); rely = (ylim[1] - ydata) / (ylim[1] - ylim[0])
        ax.set_xlim([xdata - new_width * (1 - relx), xdata + new_width * relx])
        ax.set_ylim([ydata - new_height * (1 - rely), ydata + new_height * rely])

        # [FIX v5.1] Si el usuario hace zoom/pan, guarda el estado 'auto'
        if ax == self.results_ax:
            self.last_plot_xlim = ax.get_xlim()
            self.last_plot_ylim = ax.get_ylim()
            self.last_plot_aspect = 'auto'

        event.canvas.draw_idle()

    def on_press(self, event):
        ax = event.inaxes
        if not ax: return
        if (event.button == 1 and self.selection_mode is None) or event.button == 3:
            self.pan_start = (event.xdata, event.ydata); self.dragging = True; self.pan_ax = ax

    def on_release(self, event):
        # [FIX v5.1] Si el usuario hace zoom/pan, guarda el estado 'auto'
        if self.dragging and self.pan_ax == self.results_ax:
            self.last_plot_xlim = self.results_ax.get_xlim()
            self.last_plot_ylim = self.results_ax.get_ylim()
            self.last_plot_aspect = 'auto'

        self.dragging = False; self.pan_start = None; self.pan_ax = None

    def on_motion(self, event):
        if not self.dragging or event.inaxes != self.pan_ax or self.pan_start is None: return
        if event.xdata is None or event.ydata is None: return
        dx = event.xdata - self.pan_start[0]; dy = event.ydata - self.pan_start[1]
        xlim = self.pan_ax.get_xlim(); ylim = self.pan_ax.get_ylim()
        self.pan_ax.set_xlim(xlim[0] - dx, xlim[1] - dx)
        self.pan_ax.set_ylim(ylim[0] - dy, ylim[1] - dy)
        self.pan_start = (event.xdata, event.ydata)
        event.canvas.draw_idle()

    def reset_zoom(self):
        if hasattr(self, 'current_file') and self.current_file:
            self.refresh_view(reset_zoom=True)
        else:
            self.ax.set_xlim(0, 10000); self.ax.set_ylim(-10000, 0); self.canvas.draw()

        if hasattr(self, 'network_data'):
            self.net_ax.clear()
            visualize_network(self.net_ax, *self.network_data[0:3], self.network_data[5])
            self.autoscale_view(self.net_ax) # Usar autoscale (llama a axis('equal'))
            self.net_canvas.draw()

        # [MODIFICADO v5.1] Resetea el estado y llama a update_plot
        if hasattr(self, 'simulation_results'):
            self.last_plot_aspect = 'equal' # Fija el estado a 'equal'
            self.update_plot() # update_plot se encargará de re-dibujar

    # ========== LÓGICA DE SELECCIÓN Y VISUALIZACIÓN ==========

    def on_click(self, event):
        if not self.selection_mode or event.inaxes != self.ax or event.button != 1: return
        x, y = event.xdata, -event.ydata
        if x is None or y is None: return
        logging.info(f"Click at: ({x:.1f}, {y:.1f}) in mode {self.selection_mode}")
        click_tolerance = 250

        if self.selection_mode == 'hide':
            elem = self.find_closest_element(x, y, click_tolerance)
            if elem:
                self.hidden_elements.append(elem)
                messagebox.showinfo("Element Hidden", f"Hidden element: {elem.get('id', 'Unknown')}")
                self.refresh_view(); return
            logging.warning("No visible element found to hide.")
        elif self.selection_mode == 'inlet':
            self.toggle_selection(x, y, self.selected_inlets, self.parser.elements['inlets'] + self.parser.elements['other'], 'circle', click_tolerance, "Inlet")
        elif self.selection_mode == 'outlet':
            self.toggle_selection(x, y, self.selected_outlets, self.parser.elements['outlets'] + self.parser.elements['other'], 'circle', click_tolerance, "Outlet")
        elif self.selection_mode == 'camera':
            cam = self.find_closest_chamber(x, y)
            if cam: self.toggle_element_in_list(cam, self.selected_cameras, "Chamber")
        elif self.selection_mode == 'channel':
            chan = self.find_closest_channel(x, y, click_tolerance * 2)
            if chan: self.toggle_element_in_list(chan, self.selected_channels, "Channel")

    def find_closest_element(self, x, y, tolerance):
        hidden_ids = [id(e) for e in self.hidden_elements]
        # Prioridad 1: Círculos
        elements_to_check = self.parser.elements['inlets'] + self.parser.elements['outlets'] + self.parser.elements['other']
        for elem in elements_to_check:
            if id(elem) in hidden_ids or elem['type'] != 'circle': continue
            if math.hypot(x - elem['center'][0], y - elem['center'][1]) < elem['radius'] + tolerance:
                return elem
        # Prioridad 2: Canales
        chan = self.find_closest_channel(x, y, tolerance * 2)
        if chan: return chan
        # Prioridad 3: Cámaras
        cam = self.find_closest_chamber(x, y)
        if cam: return cam
        return None

    def find_closest_channel(self, x, y, tolerance):
        hidden_ids = [id(e) for e in self.hidden_elements]
        best_channel = None; min_dist = float('inf')
        for channel in self.parser.elements['channels']:
            if id(channel) in hidden_ids: continue
            pts = channel['points']; x_b, y_b, w_b, h_b = channel['bounds']
            if (x_b - tolerance <= x <= x_b + w_b + tolerance) and (y_b - tolerance <= y <= y_b + h_b + tolerance):
                 distances = np.sqrt((pts[:, 0] - x)**2 + (pts[:, 1] - y)**2)
                 dist = np.min(distances)
                 if dist < min_dist and dist < (channel.get('stroke_width', 100) / 2 + tolerance):
                     min_dist = dist; best_channel = channel
        return best_channel

    def find_closest_chamber(self, x, y):
        hidden_ids = [id(e) for e in self.hidden_elements]
        for cam in self.parser.elements['cameras']:
            if id(cam) in hidden_ids or cam['type'] != 'rectangle': continue
            x_b, y_b, w_b, h_b = cam['bounds']
            # [CORREGIDO v4.6] Arreglado el typo 'y-b' -> 'y_b'
            if (x_b <= x <= x_b + w_b) and (y_b <= y <= y_b + h_b):
                return cam
        return None

    def toggle_selection(self, x, y, selection_list, element_pool, elem_type, tolerance, name):
        hidden_ids = [id(e) for e in self.hidden_elements]
        for elem in element_pool:
            if id(elem) in hidden_ids or elem['type'] != elem_type: continue
            if elem_type == 'circle':
                if math.hypot(x - elem['center'][0], y - elem['center'][1]) < elem['radius'] + tolerance:
                    self.toggle_element_in_list(elem, selection_list, name); return
        logging.warning(f"No {name} element found at click position.")

    def toggle_element_in_list(self, elem, elem_list, name):
        selected_ids = [id(e) for e in elem_list]; elem_id = elem.get('id', 'Unknown')
        if id(elem) not in selected_ids:
            elem_list.append(elem)
            messagebox.showinfo(f"{name} Selected", f"Selected {name.lower()}: {elem_id}")
        else:
            elem_list[:] = [e for e in elem_list if id(e) != id(elem)]
            messagebox.showinfo(f"{name} Deselected", f"Deselected {name.lower()}: {elem_id}")
        self.refresh_view()

    def set_selection_mode(self, mode):
        self.selection_mode = mode
        if mode == 'hide':
            self.selection_label.config(text="Mode: HIDE ELEMENT")
        else:
            self.selection_label.config(text=f"Selection: {mode.upper()} - Click to toggle")

    def clear_selection(self):
        self.selection_mode = None; self.selected_inlets = []; self.selected_outlets = []
        self.selected_channels = []; self.selected_cameras = []; self.hidden_elements = []
        self.selection_label.config(text="Selection: None"); self.refresh_view()

    def reset_hidden_elements(self):
        if not self.hidden_elements:
            messagebox.showinfo("Show All", "No elements are currently hidden."); return
        count = len(self.hidden_elements); self.hidden_elements = []
        self.refresh_view()
        messagebox.showinfo("Show All", f"{count} hidden elements are now visible.")

    def load_svg(self):
        file_path = filedialog.askopenfilename(
            title="Select SVG file", filetypes=[("SVG files", "*.svg"), ("All files", "*.*")])
        if file_path:
            if self.parser.parse_svg(file_path):
                self.hidden_elements = []; self.refresh_view(reset_zoom=True)
                messagebox.showinfo("Success", "SVG parsed successfully!"); self.notebook.select(0)
            else:
                messagebox.showerror("Error", "Failed to parse SVG file")

    def refresh_view(self, reset_zoom=False):
        try:
            xlim = self.ax.get_xlim(); ylim = self.ax.get_ylim()
            aspect = self.ax.get_aspect()
            is_zoomed = (xlim[0] != 0.0 or xlim[1] != 1.0) and not reset_zoom
            self.ax.clear()
            visualize_elements(self.ax, self.parser.elements, self.hidden_elements,
                               self.selected_channels, self.selected_cameras,
                               self.selected_inlets, self.selected_outlets)
            if is_zoomed:
                self.ax.set_xlim(xlim); self.ax.set_ylim(ylim)
                self.ax.set_aspect(aspect)
            else:
                self.autoscale_view(self.ax) # autoscale_view aplica 'axis(equal)'
            self.canvas.draw(); self.update_elements_list()
        except Exception as e:
            messagebox.showerror("Visualization Error", f"Error refreshing view: {e}")
            logging.error("Refresh view failed:", exc_info=True)

    def autoscale_view(self, ax_to_scale):
        """[MODIFICADO v4.5] Autoscala un eje dado (ax o net_ax)"""
        hidden_ids = [id(e) for e in self.hidden_elements]; all_x, all_y = [], []

        # Usar todos los elementos, no solo los seleccionados, para el autoscale
        for element_type in self.parser.elements.values():
            for element in element_type:
                if id(element) in hidden_ids: continue
                if 'bounds' in element:
                    x, y, w, h = element['bounds']; all_x.extend([x, x+w]); all_y.extend([y, y+h])
                elif 'center' in element:
                    cx, cy = element['center']; all_x.append(cx); all_y.append(cy)

        if all_x and all_y:
            margin_x = (max(all_x) - min(all_x)) * 0.1
            margin_y = (max(all_y) - min(all_y)) * 0.1
            margin = max(margin_x, margin_y, 1000) # Usar el margen más grande

            ax_to_scale.set_xlim(min(all_x) - margin, max(all_x) + margin)
            ax_to_scale.set_ylim(-max(all_y) - margin, -min(all_y) + margin)
            ax_to_scale.axis('equal') # <- Solo se llama aquí
        else:
            ax_to_scale.set_xlim(0, 10000)
            ax_to_scale.set_ylim(-10000, 0)
            ax_to_scale.axis('equal')

    # [FIX v4.9] ELIMINADA la función 'autoscale_results_view'.
    # Era la fuente del bug.

    def update_elements_list(self):
        self.tree.delete(*self.tree.get_children())
        hidden_ids = [id(e) for e in self.hidden_elements]; selected_cam_ids = [id(e) for e in self.selected_cameras]
        selected_chan_ids = [id(e) for e in self.selected_channels]; selected_in_ids = [id(e) for e in self.selected_inlets]
        selected_out_ids = [id(e) for e in self.selected_outlets]; use_sel_chan = len(self.selected_channels) > 0
        use_sel_cam = len(self.selected_cameras) > 0; use_sel_in = len(self.selected_inlets) > 0
        use_sel_out = len(self.selected_outlets) > 0
        for channel in self.parser.elements['channels']:
            length = np.sqrt((channel['end_point'][0]-channel['start_point'][0])**2 + (channel['end_point'][1]-channel['start_point'][1])**2)
            details = f"L: {length:.1f}µm, W: {channel['stroke_width']:.1f}µm"
            if id(channel) in hidden_ids: status = "HIDDEN"
            elif use_sel_chan: status = "SELECTED" if id(channel) in selected_chan_ids else "Ignored"
            else: status = "Auto-detected"
            self.tree.insert('', 'end', values=(channel['id'], f'Channel ({status})', details))
        for cam in self.parser.elements['cameras']:
            if cam['type'] == 'rectangle':
                x, y, w, h = cam['bounds']; details = f"Size: {w:.0f}x{h:.0f}µm"
                if id(cam) in hidden_ids: status = "HIDDEN"
                elif use_sel_cam: status = "SELECTED" if id(cam) in selected_cam_ids else "Ignored"
                else: status = "Auto-detected"
                self.tree.insert('', 'end', values=(cam['id'], f'Chamber ({status})', details))
        for inlet in self.parser.elements['inlets']:
            details = f"R: {inlet['radius']:.1f}µm"
            if id(inlet) in hidden_ids: status = "HIDDEN"
            elif use_sel_in: status = "SELECTED" if id(inlet) in selected_in_ids else "Ignored"
            else: status = "Auto-detected"
            self.tree.insert('', 'end', values=(inlet['id'], f'Inlet ({status})', details))
        for outlet in self.parser.elements['outlets']:
            details = f"R: {outlet['radius']:.1f}µm"
            if id(outlet) in hidden_ids: status = "HIDDEN"
            elif use_sel_out: status = "SELECTED" if id(outlet) in selected_out_ids else "Ignored"
            else: status = "Auto-detected"
            self.tree.insert('', 'end', values=(outlet['id'], f'Outlet ({status})', details))

    def clear_view(self):
        self.ax.clear(); self.ax.set_title('Microfluidic Device - Element Detection')
        self.ax.text(0.5, 0.5, "No SVG loaded", ha='center', va='center', transform=self.ax.transAxes)
        self.canvas.draw(); self.tree.delete(*self.tree.get_children())

        # [FIX v5.6] Limpiar también la nueva lista de la red
        if hasattr(self, 'network_tree'):
            self.network_tree.delete(*self.network_tree.get_children())

        self.current_file = None; self.clear_selection()

    def build_network(self):
        if not self.parser.current_file:
            messagebox.showwarning("Warning", "No SVG file loaded"); return
        try:
            # [MODIFICADO v6.2] Se leen los params para el build inicial
            mu_mPa_s = float(self.viscosity_entry.get())
            mu_Pa_s = mu_mPa_s / 1000.0
            height_um = float(self.height_entry.get())
            height_m = height_um * 1e-6

            channels_to_build = self.selected_channels if len(self.selected_channels) > 0 else None
            cameras_to_build = self.selected_cameras if len(self.selected_cameras) > 0 else None
            inlets_to_build = self.selected_inlets if len(self.selected_inlets) > 0 else None
            outlets_to_build = self.selected_outlets if len(self.selected_outlets) > 0 else None

            nodes, node_types, edges, inlet_nodes, outlet_nodes, cameras = self.builder.build_network(
                self.parser.elements, height_m, mu_Pa_s, inlets_to_build,
                outlets_to_build, channels_to_build, cameras_to_build)

            self.network_data = (nodes, node_types, edges, inlet_nodes, outlet_nodes, cameras)
            visualize_network(self.net_ax, nodes, node_types, edges, cameras)

            self.autoscale_view(self.net_ax)
            self.net_canvas.draw()

            # [FIX v5.6] Poblar la nueva lista de componentes
            self.update_network_list()

            messagebox.showinfo("Success", f"Network built: {len(nodes)} nodes, {len(edges)} edges")
            self.notebook.select(1)
        except Exception as e:
            messagebox.showerror("Network Error", f"Error building network: {e}")
            logging.error("Build network failed:", exc_info=True)

    # --- INICIO DEL FEATURE v5.6 ---
    def update_network_list(self):
        """Puebla la lista de componentes de red en la Tab 2."""
        if hasattr(self, 'network_tree'):
            self.network_tree.delete(*self.network_tree.get_children())

        if not hasattr(self, 'network_data'):
            return

        edges = self.network_data[2]
        for e in edges:
            if e['type'] == 'channel':
                e_id = e.get('id', 'N/A')
                # Determinar si es Cámara o Canal
                e_type = 'Chamber' if 'Chamber' in e_id else 'Channel'

                vals = (
                    e_id,
                    e_type,
                    f"{e['length_um']:.1f}",
                    f"{e['width_um']:.1f}",
                    f"{e['R']:.3e}"
                )
                self.network_tree.insert('', 'end', values=vals)
    # --- FIN DEL FEATURE v5.6 ---

    def run_simulation(self):
        if not hasattr(self, 'network_data'):
            messagebox.showwarning("Warning", "Please build network first"); return
        try:
            # [FIX v6.2] LEER los parámetros físicos CADA VEZ que se simula.
            # Este era el bug. Se leían solo en build_network.
            mu_mPa_s = float(self.viscosity_entry.get())
            mu_Pa_s = mu_mPa_s / 1000.0
            height_um = float(self.height_entry.get())

            nodes, node_types, edges, inlet_nodes, outlet_nodes, cameras = self.network_data

            # [FIX v6.2] RECALCULAR las resistencias de la red con los nuevos parámetros.
            logging.info(f"Recalculating resistances with H={height_um}µm, Visc={mu_mPa_s}mPa·s")
            for edge in edges:
                if edge['type'] == 'channel':
                    # Llama a la función de resistencia del builder
                    edge['R'] = self.builder.calculate_resistance(
                        edge['length_um'],
                        edge['width_um'],
                        height_um, # Pasa la altura en µm
                        mu_Pa_s    # Pasa la viscosidad en Pa·s
                    )

            # [FIX v6.2] Actualizar la lista de la UI con las nuevas resistencias
            self.update_network_list()

            # --- El resto de la simulación ---

            if not inlet_nodes: messagebox.showerror("Simulation Error", "No inlets found."); return
            if not outlet_nodes: messagebox.showerror("Simulation Error", "No outlets found."); return

            inlet_node = inlet_nodes[0]; outlet_node = outlet_nodes[0]
            p_out = float(self.outlet_pressure_entry.get())
            final_conditions = []

            if self.inlet_type.get() == 'flow':
                logging.info("Running in 'Flow' mode. Calculating R_eq...")
                q_target_ul_min = float(self.inlet_value_entry.get())
                q_target_m3s = q_target_ul_min * 1e-9 / 60.0

                # Crear una copia 'temporal' de las edges para el test
                test_edges = [e.copy() for e in edges]

                test_conditions = [{'node': inlet_node, 'type': 'pressure', 'value': 1.0},
                                   {'node': outlet_node, 'type': 'pressure', 'value': p_out}]
                _, solved_test_edges = solve_network_poiseuille(
                    nodes, node_types, test_edges, [inlet_node], [outlet_node], test_conditions)

                q_test_m3s = 0
                for edge in solved_test_edges:
                    if edge['n1'] == inlet_node: q_test_m3s += edge['Q_m3s']
                    elif edge['n2'] == inlet_node: q_test_m3s -= edge['Q_m3s']

                if abs(q_test_m3s) < 1e-20:
                    messagebox.showerror("Simulation Error", "Test run resulted in zero flow. Network is likely disconnected.")
                    return

                R_eq = (1.0 - p_out) / q_test_m3s
                p_required = (q_target_m3s * R_eq) + p_out
                logging.info(f"Test Q: {q_test_m3s*1e9*60:.4f} µL/min @ 1 Pa; R_eq: {R_eq:.2e} Pa·s/m³")
                logging.info(f"Required P_inlet for {q_target_ul_min} µL/min: {p_required:.2f} Pa")
                final_conditions = [{'node': inlet_node, 'type': 'pressure', 'value': p_required},
                                    {'node': outlet_node, 'type': 'pressure', 'value': p_out}]
            else:
                logging.info("Running in 'Pressure' mode.")
                p_in = float(self.inlet_value_entry.get())
                final_conditions = [{'node': inlet_node, 'type': 'pressure', 'value': p_in},
                                    {'node': outlet_node, 'type': 'pressure', 'value': p_out}]

            # [FIX v6.2] Pasa los 'edges' actualizados (con R recalculado) al solver
            pressures, final_edges = solve_network_poiseuille(
                nodes, node_types, edges, inlet_nodes, outlet_nodes, final_conditions)

            self.simulation_results = (pressures, final_edges, nodes, node_types, cameras)
            self.display_results(pressures, final_edges)

            # [FIX v5.1] Resetea el estado a 'equal' en cada nueva simulación
            self.last_plot_aspect = 'equal'
            self.update_plot() # Llama a update_plot para hacer el dibujo inicial

            messagebox.showinfo("Success", "Simulation completed successfully!")
            self.notebook.select(2)
        except Exception as e:
            messagebox.showerror("Simulation Error", f"Error during simulation: {e}")
            logging.error("Simulation failed:", exc_info=True)

    def update_plot(self, event=None):
        """[MODIFICADO v5.3] Lógica de actualización estable con bifurcación de estado."""
        if not hasattr(self, 'simulation_results'):
            logging.info("No simulation results to plot."); return

        pressures, edges, nodes, node_types, cameras = self.simulation_results

        # [FIX v5.3] La limpieza de la colorbar AHORA se hace en visualize_results

        self.results_ax.clear() # Limpiar el eje principal

        if self.plot_mode.get() == 'pressure':
            cmap = self.pressure_cmap.get()
            scale = self.pressure_scale.get()
        else:
            cmap = self.flow_cmap.get()
            scale = self.flow_scale.get()

        # 'visualize_results' (v5.3) ahora limpia el eje 'cax' viejo
        # y dibuja el nuevo en la posición fija.
        self.colorbar = visualize_results(
            self.results_fig, self.results_ax,
            pressures, edges, nodes, node_types, cameras,
            plot_mode=self.plot_mode.get(),
            cmap_name=cmap,
            scale_mode=scale
        )

        # [FIX v5.1] Lógica de bifurcación para evitar el conflicto
        if self.last_plot_aspect == 'auto':
            # Estado 'auto': El usuario hizo zoom/pan. Restaurar límites.
            self.results_ax.set_xlim(self.last_plot_xlim)
            self.results_ax.set_ylim(self.last_plot_ylim)
            self.results_ax.set_aspect('auto')
        else:
            # Estado 'equal': Vista por defecto. Dejar que Matplotlib auto-escale.
            self.results_ax.axis('equal')
            # Y guardamos este nuevo estado 'equal' para la próxima vez
            self.last_plot_xlim = self.results_ax.get_xlim()
            self.last_plot_ylim = self.results_ax.get_ylim()

        self.results_canvas.draw()


    def display_results(self, pressures, edges):
        self.results_text.delete(1.0, tk.END)
        result_text = "MICROFLUIDIC NETWORK SIMULATION RESULTS\n" + "=" * 50 + "\n\n"
        inlet_flow = 0
        if hasattr(self, 'network_data'):
            inlet_node = self.network_data[3][0]
            for e in edges:
                if e['n1'] == inlet_node: inlet_flow += e['Q_uLmin']
                elif e['n2'] == inlet_node: inlet_flow -= e['Q_uLmin']
            result_text += f"TOTAL INLET FLOW: {inlet_flow:.6f} µL/min\n"
            result_text += f"TOTAL INLET PRESSURE: {pressures[inlet_node]:.2f} Pa\n\n"

        result_text += "COMPONENT FLOWS & RESISTANCE:\n" + "-" * 30 + "\n"
        for e in edges:
            if e['type'] == 'channel':
                result_text += f"ID: {e.get('id', 'N/A')}\n"
                result_text += f"  Flow: {e['Q_uLmin']:.6f} µL/min\n"
                result_text += f"  ΔP: {e['deltaP']:.2f} Pa\n"
                result_text += f"  Resistance: {e['R']:.2e} Pa·s/m³\n\n"

        result_text += "NODE PRESSURES:\n" + "-" * 30 + "\n"
        for i, pressure in enumerate(pressures):
            result_text += f"Node {i}: {pressure:.2f} Pa\n"
        self.results_text.insert(1.0, result_text)

    def export_results(self):
        if not hasattr(self, 'simulation_results'):
            messagebox.showwarning("Warning", "No simulation results to export"); return
        try:
            pressures, edges, nodes, node_types, cameras = self.simulation_results
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"microfluidic_simulation_{timestamp}.csv"
            with open(filename, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(['edge_id', 'type', 'n1', 'n2', 'length_um', 'width_um',
                               'Q_uL_per_min', 'deltaP_Pa', 'avg_pressure_Pa', 'R_Pa_s_m3'])
                for e in edges:
                    writer.writerow([
                        e.get('id'), e.get('type', 'channel'), e['n1'], e['n2'],
                        e['length_um'], e['width_um'], e['Q_uLmin'],
                        e['deltaP'], e['avg_pressure'], e['R']
                    ])
            messagebox.showinfo("Export Complete", f"Results exported to {filename}")
        except Exception as e:
            messagebox.showerror("Export Error", f"Error exporting results: {e}")

    def export_simulation_image(self):
        """Guarda la vista actual del gráfico de simulación como un PNG de alta resolución."""
        if not hasattr(self, 'simulation_results'):
            messagebox.showwarning("Warning", "No simulation results to export.")
            return
        try:
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = filedialog.asksaveasfilename(
                title="Save Simulation Image",
                initialfile=f"simulation_plot_{timestamp}.png",
                defaultextension=".png",
                filetypes=[("PNG files", "*.png"), ("All files", "*.*")]
            )
            if filename:
                # [FIX v5.1] Asegurarse de que el gráfico esté en su estado
                # final antes de guardar.

                # Guardar el estado actual por si acaso
                temp_aspect = self.last_plot_aspect
                temp_xlim = self.last_plot_xlim
                temp_ylim = self.last_plot_ylim

                # Forzar un redibujado en modo 'equal' para la exportación
                self.last_plot_aspect = 'equal'
                self.update_plot()

                self.results_fig.savefig(filename, dpi=300, bbox_inches='tight')
                messagebox.showinfo("Export Complete", f"Simulation image saved to {filename}")

                # Restaurar el estado de zoom del usuario
                self.last_plot_aspect = temp_aspect
                if self.last_plot_aspect == 'auto':
                    self.last_plot_xlim = temp_xlim
                    self.last_plot_ylim = temp_ylim
                    self.update_plot() # Redibujar en el estado de zoom

        except Exception as e:
            messagebox.showerror("Export Error", f"Error exporting image: {e}")

if __name__ == "__main__":
    root = tk.Tk()
    app = IntegratedMicrofluidicApp(root)
    root.mainloop()
