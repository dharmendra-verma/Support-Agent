# Extraction few-shot pack (SA-18)

Prepend these examples to the extraction request (alongside the SA-17 normalization rules).
They cover varied document structures so the model maps unusual layouts to the right fields
instead of leaving required fields null. **Use null for anything genuinely absent — these
examples teach structure, not invention.**

### Example 1 — invoice with line items (totals must reconcile)
Document:
```
Brightworks LLC   Invoice 88-2
Issued 2026-02-01   Due 2026-02-15
Widget x2 .......... 40.00
Setup fee ......... 60.00
TOTAL: $100.00
```
extract_invoice:
```json
{"invoice_number":"88-2","vendor":"Brightworks LLC","invoice_date":"2026-02-01",
 "due_date":"2026-02-15","total_amount":100.00,"currency":"USD",
 "line_items":[{"description":"Widget x2","amount":40.00},{"description":"Setup fee","amount":60.00}]}
```

### Example 2 — sparse invoice (most fields absent → null, not guessed)
Document: `"Amount due: 42 EUR"`
extract_invoice:
```json
{"invoice_number":null,"vendor":null,"invoice_date":null,"due_date":null,
 "total_amount":42.00,"currency":"EUR","line_items":null}
```

### Example 3 — damage report with a category that doesn't fit (use other + detail)
Document: `"Order 98765 arrived ruined by what looks like a chemical spill"`
extract_damage_report:
```json
{"order_id":"98765","damage_type":"other","damage_type_other":"chemical spill",
 "severity":"total_loss","description":"arrived ruined by a chemical spill"}
```

### Example 4 — ambiguous source (use unclear, never invent)
Document: `"Customer says the item broke but didn't say how"`
extract_damage_report:
```json
{"order_id":null,"damage_type":"unclear","damage_type_other":null,
 "severity":"unclear","description":"item broke, cause not stated"}
```

## Before/after (record live results)
Run the SA-17 corpus through extraction **without** this pack, then **with** it, and record
the count of wrongly-null required fields each way. Expectation: the pack measurably reduces
null-extraction errors on unusual-structure documents. (Live, needs `ANTHROPIC_API_KEY`.)
