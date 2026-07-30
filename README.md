# TPVM spike

A test rig for **temporal psychovisual modulation** — displaying an image that
looks normal to a human eye but degrades when a camera photographs the screen.
  
This is a research spike, not a product. Its only job is to answer one question
on real hardware before any real engineering starts:

> Does complementary subframe modulation produce meaningful camera-side damage
> at an amplitude the eye can tolerate — and does it survive the obvious attacks?

If the answer is no, that's a cheap and useful no.

---

## The problem

Screenshot blocking (`SetWindowDisplayAffinity` on Windows, `FLAG_SECURE` on
Android) works by refusing to hand pixels to the capture path. It is a software
contract, and it has an obvious hole: point a phone at the screen. The photons
have already left. No amount of OS cooperation reaches them.

Closing that hole means attacking the analogue gap itself — making the light
leaving the panel carry information the eye reconstructs and a sensor doesn't.

## Why that is possible at all

Eyes and sensors do not form images the same way.

| | human eye | digital sensor |
|---|---|---|
| temporal | continuous integration of the light field | discrete sampling at a fixed exposure |
| readout | whole field at once | rolling shutter, row by row, staggered |
| sampling grid | irregular cone mosaic | perfectly regular Bayer array |
| spectrum | ~400–700nm, hard cutoff | responds into near-IR |

Every row is an exploitable asymmetry. This rig uses the first two.

Modern panels also have temporal resolution far beyond what we can perceive,
which is the headroom the whole technique spends. A 240Hz panel emits four
distinct states in the time your visual system registers one.

## The mechanism

Decompose each source frame `I` into complementary subframes:

```
A = I + T
B = I − T
```

Present them on consecutive refreshes. Your visual system integrates:
`(A + B) / 2 = I`. Clean image. A camera does not integrate the same way, so
it sees `T` — as banding, colour fringing, or moiré depending on the pattern.

Two implementation details are not optional:

**Do the arithmetic in linear light.** Framebuffers are sRGB-encoded; your eye
integrates photons. `EOTF(I+T) + EOTF(I−T) ≠ 2·EOTF(I)` — the curve is convex,
so the error biases bright and you get a milky lift across the whole frame. The
shader linearises, decomposes, then re-encodes. This is the single most common
way a first implementation fails, and it fails subtly enough to look like a
panel problem.

**Never drop a subframe.** Complementarity is only true across a complete set.
Miss one present and `T` appears on screen unopposed — a full-field pattern
flash, clearly visible. This is why the browser is the wrong final home for
this (see *Limits*), and why the harness reports dropped frames prominently.

## Where the protection actually comes from

Not from the eye/camera difference alone. A phone at 1/60s integrates eight
subframes off a 240Hz panel — four A, four B — and averages back to a clean
image, exactly as your retina does.

The damage comes from **rolling shutter**. Each row begins its exposure at a
different offset, so rows land at different modulation phases and band against
each other. Which implies the counter: an exposure equal to an integer multiple
of the modulation period nulls the effect. LiShield used precisely that
relationship as its *authorisation* channel — an approved camera is told the
frequency and dials in a matching exposure.

So a fixed-frequency waveform is defeated by a fixed exposure setting. Real
protection needs randomised waveforms and multiple simultaneous frequency
components, so no single exposure nulls them all. Testing that claim is what
this rig is for.

## The cost, stated honestly

This is not free. Every honest viewer pays, permanently:

- **Contrast.** `T` needs headroom to swing into. Fixed-headroom mode compresses
  the signal into ~[0.16, 0.84] linear — no true black, no true white. On OLED
  you have just discarded the panel's best property. Adaptive mode preserves the
  endpoints but leaves protection weakest in the deepest shadows and brightest
  highlights, so an attacker crops to the sky and gets a usable frame.
- **Motion.** The subframe set assumes a static scene across its duration. On a
  fast pan, A and B sample different scene states and moving edges fringe.
- **Comfort.** Modulation above conscious flicker fusion still smears into
  dotted trails during saccades (phantom array), and still contributes to eye
  strain and headaches. Photosensitive epilepsy is a hard ceiling on amplitude
  and frequency, not a warning label.
- **Panel dependence.** LCD grey-to-grey of 1–5ms against a 4.16ms subframe
  smears A into B, softening the effect for the camera as well as the eye. OLED
  switches fast enough but many OLEDs already run PWM dimming, so you are
  stacking modulation on modulation.

You are spending visible, permanent picture quality on every legitimate viewer
to impose a probabilistic cost on an illegitimate one. That trade only makes
sense where content value dominates image quality: cinema, trading floors,
secure document terminals, clinical review stations. It does not make sense
anywhere picture quality is the product.

## Limits this cannot cross

- **Global shutter defeats it entirely.** No row stagger, no banding. The
  LiShield authors state protection against global-shutter sensors is impossible
  for this class of technique. It is a phone-in-the-audience defence, not a
  defence against a determined attacker with the right camera.
- **A camera can out-sample an eye.** Record at 1000fps and you have captured
  strictly more information than a retina did in the same second — enough to
  reconstruct in post. The only durable answer is making capture genuinely
  *lossy* (saturating the sensor so data is destroyed, not merely scrambled)
  rather than merely scrambled.
- **This is layer three of three.** Encryption stops the digital copy. OS
  affinity flags stop the screenshot. Modulation stops the camera. Shipping
  layer three alone is an expensive way to degrade contrast for honest viewers.

---

## The two tools

They are **not** coupled at runtime. There is no server, no IPC, no shared
process. They are the two ends of one physical experiment, and the coupling is
entirely through files you carry between them:

```
  emitter.html                    reference.png ──┐
  (browser, fullscreen)     ──S──▶                │
        │                                         ├──▶ attack.py ──▶ SSIM score
        │  photons                                │                  best_recovery.png
        ▼                                         │
    your phone            ──────▶ capture.mp4 ────┘
```

`emitter.html` writes `reference.png` (the unmodulated source, your ground
truth). Your phone writes `capture.mp4`. `attack.py` reads both and reports how
close an attacker can get back to the reference.

That's the whole contract. Two arguments on a command line.

### emitter.html

Single file, no build, no dependencies. WebGL2 fragment shader performing the
linear-light decomposition, plus frame-timing telemetry.

| key | |
|---|---|
| `M` | modulation on/off — **off is your control capture** |
| `1`–`4` | pattern: uniform · 12px bars · 1px checker · opposed chroma |
| `↑` `↓` | amplitude ±0.05 |
| `H` | headroom: adaptive (keeps endpoints) vs fixed 16% (uniform protection) |
| `S` | save `reference.png` |
| `F` | fullscreen |
| `Tab` | hide the panel — **do this before capturing** |

Drag any image onto the window to replace the built-in chart.

The built-in chart is not decorative. The grey wedge is the SSIM anchor. The
frequency sweep is where destriping artefacts surface first. The near-black
patches are where adaptive headroom leaves you most exposed. The descending
text sizes are the honest quality metric — legibility, not a number. The white
corner squares are registration marks for the rectification step.

### attack.py

```bash
pip install opencv-python scikit-image numpy
python attack.py capture_1_60.mp4 reference.png
```

Click the four registration squares (TL, TR, BR, BL), press ENTER. Every frame
is rectified to the reference geometry, then five attacks run:

1. **best single frame** — the zero-effort attack
2. **N-frame averaging** (2/4/8/16/32) — defeats naive complementarity outright
   once N spans a full modulation period
3. **temporal median** — rejects outlier bands better than the mean
4. **FFT row-notch** — rolling-shutter banding is a narrow band of vertical
   spatial frequency and notches cleanly
5. **flat-field divide** — estimate the illumination profile from the temporal
   mean and remove it; this is the one that beats fixed-phase modulation

Each result is scored by SSIM against the reference, with per-channel gain and
offset fitted out first. Exposure and white-balance differences are free for an
attacker to correct, so counting them as damage would flatter the protection.

```
   SSIM   verdict      attack
----------------------------------------------------------
 0.9124   ATTACK WON   mean of 8 frames
 0.7733   degraded     FFT row-notch, 1 frame
 0.4192   held         single frame #0
```

`< 0.60` held · `0.60–0.85` degraded · `> 0.85` the attack won.

It also writes `best_recovery.png`. Look at it. The number is not the whole
story — SSIM does not know whether the text is readable.

---

## Running the experiment

1. `S` to save `reference.png`.
2. `F`, then `Tab`. Lights off. No other screens in frame.
3. Manual camera app, **ISO and white balance locked**. Video at each exposure:
   1/30, 1/60, 1/120, 1/250, 1/1000. Ten seconds each.
4. `M` to disable modulation, shoot one more at 1/60. **This is the control.**
5. Look at the screen yourself. Sweep your eyes across it — smearing trails
   mean the phantom array is showing at this amplitude.
6. Run `attack.py` on every clip.

**The number that matters is the gap between the modulated capture and the
control at the same exposure.** A low absolute SSIM proves nothing if the
control scores low too — that just means your phone took a bad photo.

Sweep amplitude to find the crossover: the lowest value where camera-side SSIM
drops below 0.60 while the screen still looks acceptable to you. If no such
value exists on your hardware, the technique does not work here, and that is the
result.

## Reading the timing panel

The browser cannot guarantee frame-accurate present. Chromium's Viz compositor
owns the swapchain; `requestAnimationFrame` is vsync-aligned but not
frame-accurate-*guaranteed*; at 240Hz the entire budget per subframe is 4.16ms.

So the panel is a gate, not a measurement:

- **Below 100Hz** — stop. Two-frame complementarity cycles at half refresh and
  will flicker visibly. Find a 120Hz+ panel.
- **Drops climbing, or jitter above ~15% of nominal** — you are not testing
  modulation, you are testing the compositor. Close everything, disable VRR.
- **Stable** — capture against it.

A good result here is permission to build the native version. It is not the
result. Production needs a D3D12/Vulkan flip-model swapchain, exclusive
fullscreen, and a waitable swapchain object so you block on the right moment
rather than racing it.

## What this does not do

It does not accept media and return protected media. **There is no such
artefact.** If you encoded A/B subframes into a file, anyone could average two
adjacent frames and recover `I` exactly — one line of ffmpeg, from a file you
quadrupled the bitrate to produce (A→B deltas are anti-correlated, so inter-frame
prediction collapses). Upload it anywhere that re-encodes to 60fps and the
platform performs the attack for you, for free.

The subframes can only ever exist as photons. They must be generated at present
time, in-process, from a stream decrypted in memory. Anything else is a
self-defeating file format.

## References

- Zhai & Wu, *Defeating Camcorder Piracy by Temporal Psychovisual Modulation*,
  Journal of Display Technology 10(9), 2014
- Wu & Zhai, *Temporal Psychovisual Modulation: A New Paradigm of Information
  Display*, IEEE Signal Processing Magazine 30(1), 2013
- Zhu, Zhang & Zhang, *LiShield: Automating Visual Privacy Protection Using a
  Smart LED*, ACM MobiCom 2017 — source of the rolling-shutter analysis and the
  global-shutter limit
- IEEE 1789-2015, *Recommended Practices for Modulating Current in
  High-Brightness LEDs for Mitigating Health Risks to Viewers* — read this
  before choosing amplitude and frequency

## Status

Spike. Nothing here is a component of a shippable system. The browser emitter
exists to produce a yes/no on real hardware cheaply; a yes means writing the
native emitter, which is where the actual engineering lives.
