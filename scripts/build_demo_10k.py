"""Generate a realistic 10 page 10-K PDF for demo purposes.
Synthetic but accurate in structure: title page, Items 1, 1A, 7 (MD&A with a
revenue table), Item 8 snippet, governance page.
"""
from pathlib import Path
import fitz

OUT = Path(__file__).resolve().parents[1] / "samples" / "demo-10k-real.pdf"
OUT.parent.mkdir(parents=True, exist_ok=True)

COMPANY = "Acme Industries, Inc."
PERIOD = "Fiscal Year Ended September 30, 2023"

doc = fitz.open()

def page(lines, *, title=None, size=11, y0=72, gap=18):
    p = doc.new_page(width=612, height=792)  # US Letter
    y = y0
    if title:
        p.insert_text((72, y), title, fontsize=16, fontname="helv")
        y += gap * 2
    for line in lines:
        p.insert_text((72, y), line, fontsize=size, fontname="helv")
        y += gap
        if y > 740: break

# Page 1 — Cover
page([
    "",
    "FORM 10-K",
    "",
    f"ANNUAL REPORT PURSUANT TO SECTION 13 OR 15(d)",
    f"OF THE SECURITIES EXCHANGE ACT OF 1934",
    "",
    f"For the fiscal year ended September 30, 2023",
    "",
    f"Commission File Number: 001-12345",
    "",
    f"{COMPANY}",
    "",
    "(Exact name of Registrant as specified in its charter)",
    "",
    "Delaware                                            94-1234567",
    "(State of incorporation)                            (I.R.S. Employer ID)",
    "",
    "Independent Registered Public Accounting Firm: Ernst and Young LLP",
], title="")

# Page 2 — Item 1 Business (start)
page([
    "Acme Industries, Inc. (the Company, we, or Acme) designs, manufactures, and",
    "markets industrial automation equipment and related software to customers in",
    "more than forty countries. The Company was incorporated in Delaware in 1987",
    "and is headquartered in San Francisco, California.",
    "",
    "Products. Our principal product lines include programmable logic controllers,",
    "robotic arms for precision assembly, machine vision systems, and factory",
    "operations software sold under the AcmeOS brand. Software revenue represented",
    "thirty one percent of total revenue in fiscal 2023.",
    "",
    "Markets. The Company sells primarily to automotive, consumer electronics,",
    "pharmaceutical, and logistics customers. Our three largest customers",
    "accounted for approximately twenty eight percent of revenue in fiscal 2023.",
    "",
    "Employees. As of September 30, 2023, the Company had approximately 12,400",
    "full time employees worldwide, of whom roughly forty percent were engaged in",
    "research and development.",
], title="Item 1. Business")

# Page 3 — Item 1 Business continued
page([
    "Research and Development. The Company invested $842 million in research and",
    "development during fiscal 2023, representing 10.2 percent of total revenue.",
    "Key focus areas include on device AI inference for vision systems, next",
    "generation servomotor control, and cloud connected factory analytics.",
    "",
    "Manufacturing. Final assembly for the Company's hardware products occurs at",
    "facilities in Monterrey, Mexico; Penang, Malaysia; and Austin, Texas. The",
    "Company sources semiconductors, sensors, and precision machined components",
    "from a global supplier base; certain critical components are single sourced.",
    "",
    "Intellectual Property. As of September 30, 2023, the Company held 3,214",
    "issued patents worldwide and had an additional 1,108 patent applications",
    "pending. The AcmeOS trademark is registered in 38 jurisdictions.",
    "",
    "Sustainability. The Company committed in 2022 to reach net zero operational",
    "emissions by 2030. In fiscal 2023, 73 percent of electricity consumed at",
    "Company facilities came from renewable sources.",
], title="")

# Page 4 — Item 1A Risk Factors
page([
    "An investment in our common stock involves a high degree of risk. The risks",
    "described below are not the only risks we face.",
    "",
    "Supply chain concentration. A meaningful portion of our semiconductor supply",
    "is sourced from a small number of foundries located in East Asia. Geopolitical",
    "tension, natural disaster, or export restriction affecting these foundries",
    "could materially disrupt production and revenue.",
    "",
    "Customer concentration. Our three largest customers represented approximately",
    "28 percent of revenue in fiscal 2023. Loss of any of these customers, or",
    "meaningful reduction in their orders, could have a material adverse effect.",
    "",
    "Cybersecurity. We experienced one material cybersecurity incident during",
    "fiscal 2023, in which an unauthorized third party accessed a subset of",
    "employee personally identifiable information. The Company promptly notified",
    "affected individuals and does not believe the incident had a material",
    "financial impact. We continue to invest in detection and response capability.",
    "",
    "Regulatory. Certain of our products are subject to export control regulation.",
    "Changes in such regulation could limit our ability to sell to customers in",
    "certain jurisdictions.",
], title="Item 1A. Risk Factors")

# Page 5 — Item 7 MD&A overview
page([
    "The following discussion should be read together with the consolidated",
    "financial statements and related notes included elsewhere in this Annual",
    "Report on Form 10-K.",
    "",
    "Overview. Fiscal 2023 was a year of continued growth across all product lines,",
    "with particular strength in our software segment. Total revenue reached",
    "$8,253 million, an increase of 9.4 percent compared to fiscal 2022. Operating",
    "margin expanded to 19.7 percent from 17.1 percent in the prior year, driven",
    "by mix shift toward software and operating leverage on fixed costs.",
    "",
    "Revenue by segment. Industrial Automation revenue was $5,694 million, up 6.1",
    "percent year over year. Software and Services revenue reached $2,559 million,",
    "up 17.8 percent, reflecting strong new customer acquisition and expansion",
    "within the installed base.",
    "",
    "Gross margin improved by 140 basis points to 54.3 percent, reflecting the",
    "continued mix shift toward software and ongoing cost productivity initiatives.",
    "Research and development spending grew 11 percent year over year, keeping",
    "pace with revenue growth.",
], title="Item 7. Management's Discussion and Analysis")

# Page 6 — Revenue table
p = doc.new_page(width=612, height=792)
p.insert_text((72, 72), "Item 7. MD&A (continued) — Revenue by Segment",
              fontsize=14, fontname="helv")
p.insert_text((72, 110),
              "The following table presents revenue by reportable segment ($ in millions):",
              fontsize=11, fontname="helv")

# Simple ruled table
rows = [
    ["Segment",               "FY2023",   "FY2022",   "Change %"],
    ["Industrial Automation", "5,694",    "5,368",    "+6.1 %"],
    ["Software and Services", "2,559",    "2,172",    "+17.8 %"],
    ["Other",                 "  —",      "  —",      "  —"],
    ["Total revenue",         "8,253",    "7,540",    "+9.4 %"],
]
col_x = [72, 260, 360, 460]
row_y = 150
for i, row in enumerate(rows):
    bold = (i == 0) or (row[0] == "Total revenue")
    for xi, cell in enumerate(row):
        p.insert_text((col_x[xi], row_y), cell, fontsize=11,
                      fontname=("hebo" if bold else "helv"))
    # underline header and total
    if i == 0 or row[0] == "Total revenue":
        p.draw_line((72, row_y + 4), (540, row_y + 4))
    row_y += 24

# Key metrics summary
p.insert_text((72, 330), "Key metrics summary:", fontsize=12, fontname="hebo")
metrics = [
    "Total revenue              $8,253 million   (+9.4 percent YoY)",
    "Gross margin               54.3 percent     (+140 bps)",
    "Operating margin           19.7 percent     (from 17.1 percent)",
    "Net income                 $1,318 million   (+18.2 percent)",
    "Diluted EPS                $4.27            (from $3.61)",
    "Cash from operations       $1,980 million",
    "Capital expenditure        $512 million",
    "Research and development   $842 million     (10.2 percent of revenue)",
]
y = 360
for m in metrics:
    p.insert_text((72, y), m, fontsize=11, fontname="helv")
    y += 22

# Page 7 — MD&A liquidity
page([
    "Cash, cash equivalents, and marketable securities totaled $3,104 million at",
    "September 30, 2023, compared with $2,418 million at September 30, 2022. The",
    "Company generated $1,980 million of cash from operating activities in fiscal",
    "2023, compared with $1,611 million in the prior year.",
    "",
    "Capital expenditures were $512 million, primarily for expansion of the",
    "Monterrey and Austin manufacturing facilities and for ongoing investment in",
    "research and development infrastructure.",
    "",
    "During fiscal 2023, the Company repurchased 6.8 million shares of common",
    "stock for an aggregate $427 million under the share repurchase program",
    "authorized by the Board of Directors in November 2021. As of September 30,",
    "2023, $1,073 million remained available under the program.",
    "",
    "The Company has a $750 million senior unsecured revolving credit facility",
    "that matures in March 2027. As of September 30, 2023, there were no amounts",
    "outstanding under the facility.",
    "",
    "Contractual obligations as of September 30, 2023 include operating lease",
    "commitments of $412 million and purchase obligations of $636 million,",
    "substantially all of which are due within three years.",
], title="Item 7. MD&A (continued) — Liquidity and Capital Resources")

# Page 8 — Item 7A market risk
page([
    "Foreign currency risk. Approximately 42 percent of fiscal 2023 revenue was",
    "denominated in currencies other than the U.S. dollar, principally the euro,",
    "the British pound, the Japanese yen, and the Chinese renminbi. The Company",
    "uses foreign currency forward contracts to hedge a portion of its forecasted",
    "revenue and cost of revenue. A hypothetical 10 percent strengthening of the",
    "U.S. dollar against a basket of the Company's trading currencies would have",
    "reduced fiscal 2023 revenue by approximately $285 million.",
    "",
    "Interest rate risk. The Company's marketable securities portfolio is managed",
    "primarily to preserve principal and provide liquidity. Interest rate exposure",
    "is mitigated by maintaining a short duration profile, with weighted average",
    "duration of 1.4 years as of September 30, 2023.",
    "",
    "Commodity risk. The Company purchases metals, plastics, and electronic",
    "components on global markets. Material price increases could compress gross",
    "margin if not offset by pricing action.",
], title="Item 7A. Quantitative and Qualitative Disclosures About Market Risk")

# Page 9 — Item 8 auditor + balance sheet snippet
page([
    "Report of Independent Registered Public Accounting Firm.",
    "",
    "To the Stockholders and the Board of Directors of Acme Industries, Inc.",
    "",
    "Opinion on the Financial Statements. We have audited the accompanying",
    "consolidated balance sheets of Acme Industries, Inc. and subsidiaries as of",
    "September 30, 2023 and 2022, the related consolidated statements of",
    "operations, comprehensive income, stockholders' equity, and cash flows for",
    "each of the three years in the period ended September 30, 2023, and the",
    "related notes.",
    "",
    "In our opinion, the consolidated financial statements present fairly, in all",
    "material respects, the financial position of the Company as of September 30,",
    "2023 and 2022, and the results of its operations and its cash flows for each",
    "of the three years in the period ended September 30, 2023, in conformity",
    "with U.S. generally accepted accounting principles.",
    "",
    "Ernst and Young LLP",
    "San Francisco, California",
    "November 8, 2023",
    "",
    "We have served as the Company's auditor since 1996.",
], title="Item 8. Financial Statements and Supplementary Data")

# Page 10 — Governance
page([
    "Board of Directors.",
    "",
    "The Board currently consists of nine directors, eight of whom the Board has",
    "affirmatively determined to be independent under the listing standards of",
    "the NASDAQ Global Select Market.",
    "",
    "Chief Executive Officer.",
    "",
    "Ms. Jane Liu has served as Chief Executive Officer since January 2021 and as",
    "a director since 2019. Prior to her appointment as CEO, Ms. Liu served as",
    "Chief Operating Officer of the Company from 2017 to 2021.",
    "",
    "Committees. The Board has three standing committees: Audit, Compensation,",
    "and Nominating and Corporate Governance. Each committee is composed",
    "exclusively of independent directors.",
    "",
    "Executive Compensation. Elements of fiscal 2023 executive compensation",
    "included base salary, annual cash incentive tied to revenue and operating",
    "margin targets, and long term equity awards that vest over four years subject",
    "to continued service and, for a portion, to total shareholder return",
    "relative to a peer index.",
], title="Item 10 through 14. Directors, Officers, Governance, and Compensation")

doc.save(OUT)
print(f"wrote {OUT}  ({OUT.stat().st_size} bytes, {len(doc)} pages)")
