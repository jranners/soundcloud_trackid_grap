
## 2026-03-22 - Pulsing Gradient vs Traditional Spinners
**Learning:** The "Ethereal Engine" design philosophy calls for atmospheric depth. Traditional, hard-edged circular loading spinners disrupt this immersion. A pulsing gradient transition provides high-performance feedback while maintaining the visual heat of the interface. When replacing a spinner with an animation, `aria-busy="true"` becomes critical for screen readers to recognize the asynchronous state.
**Action:** Always prefer animated background properties (like `opacity` on a pseudo-element with a reverse gradient) over physical spinners in "void" or "glassmorphic" designs. Pair this with `aria-busy` and `pointer-events: none` to guarantee accessibility and interaction safety.
