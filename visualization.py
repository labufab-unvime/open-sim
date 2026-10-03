#!/usr/bin/env python3
"""
Módulo Visualization (v5.4)
- [FIX v5.4] Se corrige el bug de "gradiente fantasma" en el modo Flujo.
  Cuando el flujo es constante (ej. 8.0001, 7.9999), el 'norm' estiraba
  el colormap sobre un rango minúsculo, amplificando el ruido numérico.
- [FIX] Ahora, si (vmax-vmin)/vmax < 1%, se fuerza el 'norm' a centrarse
  en el promedio con un rango de +/- 1%, estabilizando el color.
"""

import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, Circle
from matplotlib import cm, colors
import numpy as np
import logging

def visualize_elements(ax, elements, hidden_elements, selected_channels,
                       selected_cameras, selected_inlets, selected_outlets):
    """Visualiza los elementos SVG parseados en el eje (ax) principal."""

    hidden_ids = [id(e) for e in hidden_elements]
    selected_cam_ids = [id(e) for e in selected_cameras]
    selected_chan_ids = [id(e) for e in selected_channels]
    selected_in_ids = [id(e) for e in selected_inlets]
    selected_out_ids = [id(e) for e in selected_outlets]

    # Plot chambers
    for cam in elements['cameras']:
        if id(cam) in hidden_ids: continue
        is_selected = id(cam) in selected_cam_ids
        fcolor = 'cyan' if is_selected else 'lightblue'
        if cam['type'] == 'rectangle':
            x, y, w, h = cam['bounds']
            rect = Rectangle((x, -y), w, -h, linewidth=2, edgecolor='blue', facecolor=fcolor, alpha=0.5, zorder=1)
            ax.add_patch(rect)
            if 'connection_points' in cam:
                for cp in cam['connection_points']: ax.plot(cp[0], -cp[1], 'bo', markersize=4, alpha=0.7)
            ax.text(x + w/2, -(y + h/2), cam.get('id', 'Chamber'), ha='center', va='center', fontsize=8,
                       bbox=dict(boxstyle="round,pad=0.3", facecolor="white", alpha=0.8), zorder=2)

    # Plot channels
    for channel in elements['channels']:
        if id(channel) in hidden_ids: continue
        is_selected = id(channel) in selected_chan_ids
        color = 'cyan' if is_selected else 'red'
        lw = 4 if is_selected else 2
        pts = channel['points']
        ax.plot(pts[:, 0], -pts[:, 1], color, linewidth=lw, zorder=5)
        ax.plot(pts[0, 0], -pts[0, 1], 'go', markersize=4, zorder=6)
        ax.plot(pts[-1, 0], -pts[-1, 1], 'ro', markersize=4, zorder=6)

    # Plot inlets/outlets/other
    all_circles = elements['inlets'] + elements['outlets'] + elements['other']
    for elem in all_circles:
        if id(elem) in hidden_ids or elem['type'] != 'circle': continue
        is_in = id(elem) in selected_in_ids
        is_out = id(elem) in selected_outlets
        is_auto_in = elem in elements['inlets']
        is_auto_out = elem in elements['outlets']

        cx, cy = elem['center']; r = elem['radius']
        color = 'lime' if is_in else 'orange' if is_out else 'green' if is_auto_in else 'red' if is_auto_out else 'gray'
        alpha = 0.7 if (is_in or is_out or is_auto_in or is_auto_out) else 0.3
        zorder = 10 if (is_in or is_out or is_auto_in or is_auto_out) else 0

        if color != 'gray' or (is_in or is_out):
            circle = Circle((cx, -cy), r, fill=True, color=color, alpha=alpha, zorder=zorder)
            ax.add_patch(circle)
            if is_in: label = 'SELECTED IN'
            elif is_out: label = 'SELECTED OUT'
            elif is_auto_in: label = 'INLET'
            elif is_auto_out: label = 'OUTLET'
            else: label = ''
            if label:
                ax.text(cx, -cy, label, ha='center', va='center', fontweight='bold', color='white', fontsize=8, zorder=zorder+1)

    ax.set_xlabel('X (µm)'); ax.set_ylabel('Y (µm)')
    ax.set_title('Microfluidic Device - (Click to Toggle Select, Right-Click-Drag to Pan)')
    ax.grid(True, alpha=0.3)
    # ax.axis('equal') # Se llama desde main_app.py

def visualize_network(ax, nodes, node_types, edges, cameras):
    """Visualiza la topología de la red en el eje (ax) de la red."""
    ax.clear()

    # Plot chambers (background)
    for cam in cameras:
        if cam['type'] == 'rectangle':
            x, y, w, h = cam['bounds']
            rect = Rectangle((x, -y), w, -h, linewidth=1, edgecolor='blue', facecolor='lightblue', alpha=0.3, zorder=1)
            ax.add_patch(rect)

    # Plot edges
    for e in edges:
        pts = e['points_m'] * 1e6
        color = 'red' if e['type'] == 'channel' else 'k--'
        lw = 2 if e['type'] == 'channel' else 1
        ax.plot(pts[:, 0], -pts[:, 1], color, linewidth=lw, alpha=0.8, zorder=5)

    # Plot nodes
    for i, (node, ntype) in enumerate(zip(nodes, node_types)):
        x, y = node[0] * 1e6, node[1] * 1e6
        color = 'red' if ntype == 'inlet' else 'blue' if ntype == 'outlet' else 'purple' if 'camera_connection' in ntype else 'gray'
        marker = 'o' if ntype in ['inlet', 'outlet'] else '^' if 'camera_connection' in ntype else '.'
        size = 80 if ntype in ['inlet', 'outlet'] else 40 if 'camera_connection' in ntype else 20
        ax.scatter(x, -y, c=color, marker=marker, s=size, zorder=10, edgecolors='black', linewidth=1)
        ax.text(x + 100, -y, f' {i}', fontsize=7, ha='left', va='center', weight='bold', zorder=11,
                bbox=dict(boxstyle="round,pad=0.2", facecolor="white", alpha=0.5, edgecolor='none'))

    ax.set_title("Network Topology"); ax.set_xlabel("X (µm)"); ax.set_ylabel("Y (µm)")
    ax.grid(True, alpha=0.3)
    # ax.axis('equal') # Se llama desde main_app.py

def visualize_results(fig, ax, pressures, edges, nodes, node_types, cameras,
                      plot_mode='pressure', cmap_name='Reds', scale_mode='log'):
    """Visualiza los resultados de la simulación. NO LLAMA A AX.CLEAR() O AX.AXIS('EQUAL')"""

    # Determinar normalización y mapa de color
    try:
        cmap = plt.colormaps[cmap_name]
    except KeyError:
        logging.warning(f"Colormap '{cmap_name}' no encontrado. Usando 'viridis'.")
        cmap = plt.colormaps['viridis']

    cbar_label = ""

    if plot_mode == 'pressure':
        cbar_label = "Pressure (Pa)"
        pvals = [p for p in pressures if p > 0]
        vmin = max(min(pvals) if pvals else 0.01, 0.01) # Evitar 0 para log
        vmax = max(pressures) if len(pressures) > 0 else 1.0
        if vmax <= vmin: vmax = vmin + 1.0

        if scale_mode == 'log':
            norm = colors.LogNorm(vmin=vmin, vmax=vmax)
            cbar_label += " (Log Scale)"
        else:
            norm = colors.Normalize(vmin=vmin, vmax=vmax)

        get_color_val = lambda e: e['avg_pressure']

    else: # Modo Flow
        cbar_label = "Flow (µL/min)"
        # [FIX v5.4] El bug de la escala de color estaba aquí.
        # Se usaba 'qvals' solo de 'channel', pero se ploteaban todos.
        # Ahora 'qvals' usa *todos* los edges que se van a plotear.
        qvals = [abs(e['Q_uLmin']) for e in edges if e['type'] == 'channel']

        vmin = min(qvals) if qvals else 0.0
        vmax = max(qvals) if qvals else 1.0

        # [FIX v5.4] Si la variación de flujo es < 1% (ruido numérico),
        # forzamos la escala a +/- 1% del promedio para estabilizar el color.
        if vmax > 0 and (vmax - vmin) / vmax < 0.01:
            logging.warning("Flow variation is < 1%. Stabilizing color scale.")
            v_avg = (vmax + vmin) / 2.0
            vmin = v_avg * 0.99
            vmax = v_avg * 1.01

        if vmax <= vmin: vmax = vmin + 1.0 # Fallback por si v_avg es 0

        if scale_mode == 'log':
            qvals_pos = [q for q in qvals if q > 0]
            vmin_log = max(min(qvals_pos) if qvals_pos else 0.01, 0.01)

            # Re-chequear la estabilización para el log
            if vmax > 0 and (vmax - vmin_log) / vmax < 0.01:
                 v_avg = (vmax + vmin_log) / 2.0
                 vmin_log = v_avg * 0.99
                 vmax = v_avg * 1.01
            if vmax <= vmin_log: vmax = vmin_log + 1.0

            norm = colors.LogNorm(vmin=vmin_log, vmax=vmax)
            cbar_label += " (Log Scale)"
        else:
            norm = colors.Normalize(vmin=vmin, vmax=vmax)

        get_color_val = lambda e: abs(e['Q_uLmin'])

    # Dibujar Cámaras
    for cam in cameras:
        if cam['type'] != 'rectangle': continue
        cam_edge = next((e for e in edges if e['id'] == cam['id']), None)
        if not cam_edge: continue
        x, y, w, h = cam['bounds']
        color_val = get_color_val(cam_edge)
        # Aplicar el color, asegurándose de que esté dentro de los límites
        color = cmap(norm(np.clip(color_val, vmin, vmax)))
        rect = Rectangle((x, -y), w, -h, linewidth=1, edgecolor='gray', facecolor=color, alpha=0.8, zorder=1)
        ax.add_patch(rect)

        if plot_mode == 'flow':
            mid_x = x + w/2
            mid_y = y + h/2
            ax.text(mid_x, -mid_y, f"{abs(cam_edge['Q_uLmin']):.2f} µL/min",
                    ha='center', va='center', fontsize=7, fontweight='bold', zorder=12,
                    bbox=dict(boxstyle="round,pad=0.2", facecolor="white", alpha=0.5, edgecolor='none'))

    # Dibujar Canales
    for e in edges:
        pts = e['points_m'] * 1e6
        is_cam_edge = any(e['id'] == cam['id'] for cam in cameras)
        if is_cam_edge: continue

        if e['type'] == 'channel':
            color_val = get_color_val(e)
            # Aplicar el color, asegurándose de que esté dentro de los límites
            color = cmap(norm(np.clip(color_val, vmin, vmax)))
            ax.plot(pts[:, 0], -pts[:, 1], color=color, linewidth=4, alpha=0.8, zorder=5)

            if plot_mode == 'flow':
                mid_x = np.mean(pts[:, 0])
                mid_y = -np.mean(pts[:, 1])
                ax.text(mid_x, mid_y, f"{abs(e['Q_uLmin']):.2f} µL/min",
                        ha='center', va='center', fontsize=7, fontweight='bold', zorder=12,
                        bbox=dict(boxstyle="round,pad=0.2", facecolor="white", alpha=0.5, edgecolor='none'))

    # Plot nodes
    for i, (node, ntype) in enumerate(zip(nodes, node_types)):
        x, y = node[0] * 1e6, node[1] * 1e6
        color = 'red' if ntype == 'inlet' else 'blue' if ntype == 'outlet' else 'purple' if 'camera_connection' in ntype else 'gray'
        marker = 'o' if ntype in ['inlet', 'outlet'] else '^' if 'camera_connection' in ntype else '.'
        size = 80 if ntype in ['inlet', 'outlet'] else 40 if 'camera_connection' in ntype else 20
        ax.scatter(x, -y, c=color, marker=marker, s=size, zorder=10, edgecolors='black', linewidth=1)

        if plot_mode == 'pressure':
            ax.text(x + 100, -y, f' {i}\n{pressures[i]:.1f}Pa',
                                 fontsize=7, ha='left', va='center', weight='bold', zorder=11,
                                 bbox=dict(boxstyle="round,pad=0.2", facecolor="white", alpha=0.5, edgecolor='none'))
        else:
             ax.text(x + 100, -y, f' {i}',
                                 fontsize=7, ha='left', va='center', weight='bold', zorder=11,
                                 bbox=dict(boxstyle="round,pad=0.2", facecolor="white", alpha=0.5, edgecolor='none'))

    ax.set_title(f"Simulation Results - {plot_mode.capitalize()} Distribution")
    ax.set_xlabel("X (µm)"); ax.set_ylabel("Y (µm)")
    ax.grid(True, alpha=0.3)

    # [CORREGIDO v4.4] No llamar a axis('equal') aquí. Se controla desde main_app.

    # --- INICIO DEL FIX v5.3 (basado en input de ChatGPT) ---
    # Crear colorbar fija a la derecha sin afectar el layout

    # 1. Eliminamos ejes anteriores de colorbar si existen
    for old_ax in fig.axes:
        if old_ax is not ax: # No borrar el eje principal del gráfico
            try:
                fig.delaxes(old_ax)
            except Exception as e:
                logging.warning(f"Error deleting old colorbar axes: {e}")

    # 2. Eje para la colorbar: coordenadas absolutas dentro de la figura
    cax = fig.add_axes([0.88, 0.15, 0.03, 0.70])  # [x0, y0, ancho, alto]
    sm = cm.ScalarMappable(norm=norm, cmap=cmap)
    sm.set_array([])
    cbar = fig.colorbar(sm, cax=cax)
    cbar.set_label(cbar_label)

    return cbar
    # --- FIN DEL FIX v5.3 ---
