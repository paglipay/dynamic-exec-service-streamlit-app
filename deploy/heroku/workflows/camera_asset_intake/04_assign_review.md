## Step 4: Assign camera numbers (fallback / catch-up)

Most items are already assigned by this point — the Scan step now
auto-assigns and prints a label the instant a Model+Serial pair is
captured. This step only shows what that couldn't handle: usually a
model scanned before the Camera Chart was uploaded, or one with no
matching open slot at all. It's also where to fix a scan-time
auto-assignment that turned out wrong.

For every item shown here, this step suggests the lowest open Camera
Chart slot whose model matches.

⚠️ **This matching logic hasn't been validated against a real project
yet** — it's only been checked for parsing correctness on two files
from different sites. Review every suggestion against the actual
Camera Chart (building, room, mount type) before confirming — nothing
is written until you click **Confirm this assignment**.

If a scanned item shows "No open Camera Chart slot matches this
model," it means either the Camera Chart wasn't uploaded yet (Step 2)
or no unassigned slot's model text contains this item's Model Number —
check the raw Camera Chart in Step 2's preview.
