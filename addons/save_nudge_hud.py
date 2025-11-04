# SPDX-License-Identifier: MIT
# (v0.4.4) — Save Nudge — HUD (Prefs, Autostart, Abs-Min-Step, Fade, Save-Reset)
bl_info = {
    "name": "Save Nudge — HUD (Prefs, Autostart, Abs-Min-Step, Fade, Save-Reset)",
    "author": "ChatGPT for Aaron",
    "version": (0, 4, 4),
    "blender": (4, 5, 0),
    "location": "Edit > Preferences > Add-ons > Save Nudge HUD; 3D View > N-Panel > Save Nudge HUD",
    "description": "Viewport HUD reminder with prefs, autostart, absolute min-step, opacity that fades with urgency, and smooth reset on save.",
    "category": "3D View",
}
import bpy, time, math
from bpy.app.handlers import persistent
import gpu
from gpu_extras.batch import batch_for_shader
import blf
from math import exp
def _prefs():
    addons = bpy.context.preferences.addons
    for key in (__name__,):
        if key in addons:
            return addons[key].preferences
    for k, mod in addons.items():
        try:
            if getattr(mod.module, "bl_info", {}).get("name") == bl_info["name"]:
                return mod.preferences
        except Exception:
            pass
    return None
DEFAULTS = dict(
    target_seconds=10.0,
    cooldown_seconds=0.5,
    w_mouse=0.0,
    w_wheel=0.25,
    w_click=0.6,
    w_key=0.5,
    hud_x=24,
    hud_y=56,
    hud_radius=16,
    ring_thickness=3,
    ring_alpha=0.90,
    text_alpha=0.98,
    show_text=True,
    show_percent=True,
    full_threshold=0.995,
    flash_period=1.0,
    flash_duty=0.5,
    auto_start=True,
    min_step_seconds=0.02,
    min_visible_alpha=0.10,
)
class _State:
    running = False
    last_tick = 0.0
    last_event = 0.0
    activity = 0.0
    intensity = 0.0
    equiv = 0.0
    draw_handle = None
    save_flash_until = 0.0
S = _State()
class SNHUD_Prefs(bpy.types.AddonPreferences):
    bl_idname = __name__
    target_seconds: bpy.props.FloatProperty(name="Target to 100% (s)", default=DEFAULTS['target_seconds'], min=5.0, soft_max=7200.0)
    cooldown_seconds: bpy.props.FloatProperty(name="Cooldown / Decay (s)", default=DEFAULTS['cooldown_seconds'], min=0.1, soft_max=30.0)
    min_step_seconds: bpy.props.FloatProperty(name="Min Step (s)", default=DEFAULTS['min_step_seconds'], min=0.0, soft_max=60.0, description="Ignore equivalent-time changes smaller than this number of seconds")
    w_mouse: bpy.props.FloatProperty(name="Weight: Mouse Move", default=DEFAULTS['w_mouse'], min=0.0, soft_max=2.0)
    w_wheel: bpy.props.FloatProperty(name="Weight: Mouse Wheel", default=DEFAULTS['w_wheel'], min=0.0, soft_max=5.0)
    w_click: bpy.props.FloatProperty(name="Weight: Mouse Click", default=DEFAULTS['w_click'], min=0.0, soft_max=5.0)
    w_key:   bpy.props.FloatProperty(name="Weight: Key Press", default=DEFAULTS['w_key'], min=0.0, soft_max=5.0)
    hud_x: bpy.props.IntProperty(name="HUD X", default=DEFAULTS['hud_x'], min=0, soft_max=4000)
    hud_y: bpy.props.IntProperty(name="HUD Y", default=DEFAULTS['hud_y'], min=0, soft_max=4000)
    hud_radius: bpy.props.IntProperty(name="HUD Size", default=DEFAULTS['hud_radius'], min=8, soft_max=64)
    ring_thickness: bpy.props.IntProperty(name="Ring Thickness", default=DEFAULTS['ring_thickness'], min=1, soft_max=10)
    ring_alpha: bpy.props.FloatProperty(name="Ring Alpha (base)", default=DEFAULTS['ring_alpha'], min=0.0, max=1.0)
    text_alpha: bpy.props.FloatProperty(name="Text Alpha (base)", default=DEFAULTS['text_alpha'], min=0.0, max=1.0)
    min_visible_alpha: bpy.props.FloatProperty(name="Min Visible Alpha (0–1)", default=DEFAULTS['min_visible_alpha'], min=0.0, max=1.0, description="Alpha floor so the HUD never fully disappears; 0.10 = 10%")
    show_text: bpy.props.BoolProperty(name="Show Text", default=DEFAULTS['show_text'], description="Enable HUD text (percentage at low priority, message at full)")
    show_percent: bpy.props.BoolProperty(name="Show Percent (when not full)", default=DEFAULTS['show_percent'])
    full_threshold: bpy.props.FloatProperty(name="Full Threshold", default=DEFAULTS['full_threshold'], min=0.5, max=1.0, description="Priority at which to flash and show 'Please save' (if text is enabled)")
    flash_period: bpy.props.FloatProperty(name="Flash Period (s)", default=DEFAULTS['flash_period'], min=0.1, max=5.0)
    flash_duty:   bpy.props.FloatProperty(name="Flash Duty", default=DEFAULTS['flash_duty'], min=0.05, max=0.95)
    auto_start: bpy.props.BoolProperty(name="Start HUD on Startup / File Load", default=DEFAULTS['auto_start'], description="Automatically start the HUD monitor when Blender launches or a file is loaded")
    def draw(self, context):
        col = self.layout.column()
        col.label(text="Timing")
        row = col.row(align=True); row.prop(self, "target_seconds"); row.prop(self, "cooldown_seconds")
        row = col.row(align=True); row.prop(self, "min_step_seconds")
        col.separator(); col.label(text="Weights (set Mouse Move to 0 to ignore)")
        row = col.row(align=True); row.prop(self, "w_mouse"); row.prop(self, "w_wheel")
        row = col.row(align=True); row.prop(self, "w_click"); row.prop(self, "w_key")
        col.separator(); col.label(text="HUD")
        row = col.row(align=True); row.prop(self, "hud_x"); row.prop(self, "hud_y")
        row = col.row(align=True); row.prop(self, "hud_radius"); row.prop(self, "ring_thickness")
        row = col.row(align=True); row.prop(self, "ring_alpha"); row.prop(self, "text_alpha")
        row = col.row(align=True); row.prop(self, "min_visible_alpha")
        row = col.row(align=True); row.prop(self, "show_text"); row.prop(self, "show_percent")
        col.separator(); col.label(text="Full Priority Behaviour")
        row = col.row(align=True); row.prop(self, "full_threshold"); row.prop(self, "flash_period")
        col.prop(self, "flash_duty")
        col.separator(); col.prop(self, "auto_start")
        col.operator("snhud.reset_defaults", text="Reset All to Defaults", icon='LOOP_BACK')
def clamp(x, a=0.0, b=1.0): return a if x < a else b if x > b else x
def priority_from_state(prefs):
    tgt = max(1e-6, float(prefs.target_seconds)); return clamp(S.equiv / tgt, 0.0, 1.0)
def visible_alpha_factor(p, prefs): return max(float(prefs.min_visible_alpha), float(p))
def color_for_priority(p, prefs, override_color=None):
    a_factor = visible_alpha_factor(p, prefs); base_a = clamp(prefs.ring_alpha, 0.0, 1.0); a = base_a * a_factor
    if override_color is not None: r, g, b = override_color; return (float(r), float(g), float(b), a)
    if p < 0.5:
        t = p / 0.5; r = 0.1 + (1.0 - 0.1) * t; g = 0.8 + (0.9 - 0.8) * t; b = 0.1 + (0.2 - 0.1) * t
    else:
        t = (p - 0.5) / 0.5; r = 1.0; g = 0.9 - (0.9 - 0.15) * t; b = 0.2 - (0.2 - 0.15) * t
    return (float(r), float(g), float(b), a)
def _shader(): return gpu.shader.from_builtin('UNIFORM_COLOR')
def draw_ring(cx, cy, r, thick, pct, col, bg_alpha_factor=1.0):
    shader = _shader(); gpu.state.blend_set('ALPHA'); steps = 96; r_in = r - thick; r_out = r + thick
    verts_bg = []
    for i in range(steps):
        a0 = 2.0 * math.pi * (i / steps); a1 = 2.0 * math.pi * ((i + 1) / steps)
        verts_bg.extend([(cx + r_in*math.cos(a0), cy + r_in*math.sin(a0)),
                         (cx + r_out*math.cos(a0), cy + r_out*math.sin(a0)),
                         (cx + r_out*math.cos(a1), cy + r_out*math.sin(a1)),
                         (cx + r_in*math.cos(a0), cy + r_in*math.sin(a0)),
                         (cx + r_out*math.cos(a1), cy + r_out*math.sin(a1)),
                         (cx + r_in*math.cos(a1), cy + r_in*math.sin(a1))])
    batch_bg = batch_for_shader(shader, 'TRIS', {'pos': verts_bg}); shader.bind(); shader.uniform_float("color", (0,0,0,0.25*bg_alpha_factor)); batch_bg.draw(shader)
    steps_w = max(1, int(steps * clamp(pct, 0.0, 1.0))); verts = []
    for i in range(steps_w):
        a0 = 2.0 * math.pi * (i / steps); a1 = 2.0 * math.pi * ((i + 1) / steps)
        verts.extend([(cx + r_in*math.cos(a0), cy + r_in*math.sin(a0)),
                      (cx + r_out*math.cos(a0), cy + r_out*math.sin(a0)),
                      (cx + r_out*math.cos(a1), cy + r_out*math.sin(a1)),
                      (cx + r_in*math.cos(a0), cy + r_in*math.sin(a0)),
                      (cx + r_out*math.cos(a1), cy + r_out*math.sin(a1)),
                      (cx + r_in*math.cos(a1), cy + r_in*math.sin(a1))])
    batch = batch_for_shader(shader, 'TRIS', {'pos': verts}); shader.bind(); shader.uniform_float("color", col); batch.draw(shader); gpu.state.blend_set('NONE')
def draw_text(prefs, x, y, text, size=14, alpha=None, shadow=True, p=1.0):
    base_alpha = prefs.text_alpha if alpha is None else alpha; a_factor = visible_alpha_factor(p, prefs); use_alpha = clamp(base_alpha * a_factor, 0.0, 1.0)
    font_id = 0; gpu.state.blend_set('ALPHA'); blf.size(font_id, int(size))
    if shadow: blf.enable(font_id, blf.SHADOW); blf.shadow(font_id, 3, 0.0, 0.0, 0.0, 0.78); blf.shadow_offset(font_id, 1, -1)
    blf.color(font_id, 1.0, 1.0, 1.0, float(use_alpha)); blf.position(font_id, int(x), int(y), 0); blf.draw(font_id, text)
    if shadow: blf.disable(font_id, blf.SHADOW); gpu.state.blend_set('NONE')
def hud_draw_callback():
    prefs = _prefs(); if not prefs: return
    p = priority_from_state(prefs); x, y = int(prefs.hud_x), int(prefs.hud_y); r = int(prefs.hud_radius * (0.9 + 0.3 * p))
    now = time.time(); col = color_for_priority(p, prefs, override_color=(0.2, 1.0, 0.35)) if now < S.save_flash_until else color_for_priority(p, prefs)
    bg_factor = visible_alpha_factor(p, prefs)
    if p >= prefs.full_threshold:
        period = max(0.1, prefs.flash_period); duty = max(0.05, min(0.95, prefs.flash_duty)); phase = (time.time() % period) / period
        if phase < duty: draw_ring(x, y, r, int(prefs.ring_thickness), p, col, bg_alpha_factor=bg_factor)
        if prefs.show_text: draw_text(prefs, x + r + 12, y - 2, "Please save", size=18, alpha=1.0, shadow=True, p=p)
    else:
        draw_ring(x, y, r, int(prefs.ring_thickness), p, col, bg_alpha_factor=bg_factor)
        if prefs.show_text and prefs.show_percent: draw_text(prefs, x + r + 10, y - 6, f"{int(p*100)}%", size=14, alpha=prefs.text_alpha, shadow=True, p=p)
class SNHUD_Monitor(bpy.types.Operator):
    bl_idname = "wm.snhud_monitor"; bl_label = "Save Nudge HUD Monitor"; _timer = None
    def _add(self, amt): S.activity += max(0.0, amt); S.last_event = time.time()
    def modal(self, context, event):
        prefs = _prefs(); if not prefs: return {'PASS_THROUGH'}
        if event.type == 'TIMER':
            now = time.time(); dt = max(1e-3, now - (S.last_tick or now)); S.last_tick = now
            tau = max(0.1, float(prefs.cooldown_seconds)); S.activity *= exp(-dt / tau); S.intensity = 1.0 - exp(-S.activity / 1.5)
            tentative_equiv = max(0.0, S.equiv + S.intensity * dt); min_step = max(0.0, float(prefs.min_step_seconds))
            if abs(tentative_equiv - S.equiv) >= min_step: S.equiv = tentative_equiv
            for win in bpy.context.window_manager.windows:
                for area in win.screen.areas:
                    if area.type == 'VIEW_3D': area.tag_redraw()
            return {'PASS_THROUGH'}
        if event.type == 'MOUSEMOVE':
            if prefs.w_mouse > 0.0: self._add(float(prefs.w_mouse))
        elif event.type in {'WHEELUPMOUSE','WHEELDOWNMOUSE','MOUSEPAN'}: self._add(float(prefs.w_wheel))
        elif event.value in {'PRESS','CLICK','DOUBLE_CLICK'}:
            if event.type in {'LEFTMOUSE','RIGHTMOUSE','MIDDLEMOUSE'}: self._add(float(prefs.w_click))
            elif event.type != 'TIMER': self._add(float(prefs.w_key))
        return {'PASS_THROUGH'}
    def execute(self, context):
        if S.running: self.report({'INFO'}, "HUD already running."); return {'RUNNING_MODAL'}
        wm = context.window_manager; self._timer = wm.event_timer_add(0.25, window=context.window); wm.modal_handler_add(self); S.running = True; S.last_tick = time.time()
        if S.draw_handle is None: S.draw_handle = bpy.types.SpaceView3D.draw_handler_add(hud_draw_callback, (), 'WINDOW', 'POST_PIXEL')
        self.report({'INFO'}, "Save Nudge HUD started."); return {'RUNNING_MODAL'}
    def cancel(self, context):
        wm = context.window_manager; if self._timer: wm.event_timer_remove(self._timer); self._timer = None
        S.running = False; self.report({'INFO'}, "Save Nudge HUD stopped.")
class SNHUD_PT_Panel(bpy.types.Panel):
    bl_space_type='VIEW_3D'; bl_region_type='UI'; bl_category="Save Nudge HUD"; bl_label="Save Nudge HUD"
    def draw(self, context):
        prefs = _prefs(); col = self.layout.column(align=True)
        col.operator("wm.snhud_monitor", text="Start HUD", icon='PLAY'); col.operator("snhud.reset", text="Reset Counters", icon='LOOP_BACK'); col.separator()
        if prefs:
            percent = int(priority_from_state(prefs)*100.0); col.label(text=f"Priority: {percent}% (equiv {S.equiv:.2f}s)")
            box = col.box(); box.label(text="Quick Tweaks")
            r = box.row(align=True); r.prop(prefs, "target_seconds"); r.prop(prefs, "cooldown_seconds")
            r = box.row(align=True); r.prop(prefs, "min_step_seconds")
            r = box.row(align=True); r.prop(prefs, "w_mouse"); r.prop(prefs, "w_wheel")
            r = box.row(align=True); r.prop(prefs, "w_click"); r.prop(prefs, "w_key")
            r = box.row(align=True); r.prop(prefs, "hud_x"); r.prop(prefs, "hud_y")
            r = box.row(align=True); r.prop(prefs, "hud_radius"); r.prop(prefs, "ring_thickness")
            r = box.row(align=True); r.prop(prefs, "ring_alpha"); r.prop(prefs, "text_alpha")
            r = box.row(align=True); r.prop(prefs, "min_visible_alpha")
            r = box.row(align=True); r.prop(prefs, "show_text"); r.prop(prefs, "show_percent")
            r = box.row(align=True); r.prop(prefs, "full_threshold"); r.prop(prefs, "flash_period")
            r = box.row(align=True); r.prop(prefs, "flash_duty")
        else: col.label(text="(Prefs unavailable — install the add-on)")
class SNHUD_Reset(bpy.types.Operator):
    bl_idname = "snhud.reset"; bl_label = "Reset Save Nudge Counters"
    def execute(self, context):
        S.activity = 0.0; S.intensity = 0.0; S.equiv = 0.0; S.last_tick = time.time(); self.report({'INFO'}, "HUD counters reset."); return {'FINISHED'}
class SNHUD_ResetDefaults(bpy.types.Operator):
    bl_idname = "snhud.reset_defaults"; bl_label = "Reset All to Defaults"
    def execute(self, context):
        prefs = _prefs()
        if prefs:
            for k, v in DEFAULTS.items(): setattr(prefs, k, v)
        S.activity = 0.0; S.intensity = 0.0; S.equiv = 0.0; S.last_tick = time.time()
        self.report({'INFO'}, "All preferences and counters reset to defaults."); return {'FINISHED'}
@persistent
def _snhud_on_save(_):
    S.save_flash_until = time.time() + 1.0
    def _fade():
        S.equiv *= 0.5; S.activity *= 0.5; S.intensity *= 0.5
        for win in bpy.context.window_manager.windows:
            for area in win.screen.areas:
                if area.type == 'VIEW_3D': area.tag_redraw()
        if S.equiv > 0.02 or S.activity > 0.02 or S.intensity > 0.02: return 0.1
        S.equiv = 0.0; S.activity = 0.0; S.intensity = 0.0; return None
    bpy.app.timers.register(_fade, first_interval=0.1)
@persistent
def _snhud_on_load(_):
    prefs = _prefs()
    if prefs and prefs.auto_start:
        def _start():
            try: bpy.ops.wm.snhud_monitor('INVOKE_DEFAULT')
            except Exception as e: print("[SaveNudgeHUD] Auto-start failed:", e)
            return None
        bpy.app.timers.register(_start, first_interval=1.0)
def _maybe_autostart_now():
    prefs = _prefs()
    if prefs and prefs.auto_start:
        try: bpy.ops.wm.snhud_monitor('INVOKE_DEFAULT')
        except Exception as e: print("[SaveNudgeHUD] Auto-start (register) failed:", e)
classes = (SNHUD_Prefs, SNHUD_Monitor, SNHUD_PT_Panel, SNHUD_Reset, SNHUD_ResetDefaults)
def register():
    for c in classes: bpy.utils.register_class(c)
    if _snhud_on_load not in bpy.app.handlers.load_post: bpy.app.handlers.load_post.append(_snhud_on_load)
    if _snhud_on_save not in bpy.app.handlers.save_post: bpy.app.handlers.save_post.append(_snhud_on_save)
    _maybe_autostart_now()
def unregister():
    try:
        if _snhud_on_load in bpy.app.handlers.load_post: bpy.app.handlers.load_post.remove(_snhud_on_load)
    except Exception: pass
    try:
        if _snhud_on_save in bpy.app.handlers.save_post: bpy.app.handlers.save_post.remove(_snhud_on_save)
    except Exception: pass
    try:
        if S.draw_handle: bpy.types.SpaceView3D.draw_handler_remove(S.draw_handle, 'WINDOW'); S.draw_handle = None
    except Exception: pass
    for c in reversed(classes):
        try: bpy.utils.unregister_class(c)
        except Exception: pass
if __name__ == "__main__": register()
