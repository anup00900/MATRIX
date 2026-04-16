"""Generate 4 synthetic but realistic 10-page annual reports covering
AMD, NVIDIA, Netflix, Ferrari so the demo can run multi-row cross-issuer.
"""
from pathlib import Path
import fitz

OUT = Path(__file__).resolve().parents[1] / "samples"
OUT.mkdir(parents=True, exist_ok=True)

ISSUERS = [
    {
        "filename": "AMD_2023_10K.pdf",
        "name": "Advanced Micro Devices, Inc.",
        "short": "AMD",
        "ceo": "Lisa Su",
        "auditor": "Ernst and Young LLP",
        "period": "December 30, 2023",
        "revenue_fy": "$22,680",
        "revenue_prev": "$23,601",
        "revenue_change": "(3.9)%",
        "gross_margin": "46.1 percent",
        "op_margin": "1.8 percent",
        "net_income": "$854",
        "eps": "$0.53",
        "cfo": "$1,668",
        "capex": "$549",
        "rnd": "$5,872 million    (25.9 percent of revenue)",
        "employees": "26,000",
        "business": "AMD is a global semiconductor company that develops high performance computing and graphics technologies including CPUs, GPUs, FPGAs, Adaptive SoCs, and AI accelerators.",
        "segment_1_name": "Data Center",
        "segment_1_rev": "6,496",
        "segment_2_name": "Client",
        "segment_2_rev": "4,651",
        "segment_3_name": "Gaming",
        "segment_3_rev": "6,212",
        "segment_4_name": "Embedded",
        "segment_4_rev": "5,321",
        "risk_1_topic": "Market concentration in data center and PC segments",
        "risk_2_topic": "Intense competition from Intel and NVIDIA",
        "risk_3_topic": "Dependence on third party foundries, principally TSMC",
        "cyber": "No material cybersecurity incidents were disclosed during fiscal 2023.",
    },
    {
        "filename": "NVIDIA_2024_10K.pdf",
        "name": "NVIDIA Corporation",
        "short": "NVDA",
        "ceo": "Jensen Huang",
        "auditor": "PricewaterhouseCoopers LLP",
        "period": "January 28, 2024",
        "revenue_fy": "$60,922",
        "revenue_prev": "$26,974",
        "revenue_change": "+125.8 percent",
        "gross_margin": "72.7 percent",
        "op_margin": "54.1 percent",
        "net_income": "$29,760",
        "eps": "$11.93",
        "cfo": "$28,090",
        "capex": "$1,069",
        "rnd": "$8,675 million    (14.2 percent of revenue)",
        "employees": "29,600",
        "business": "NVIDIA is the world leader in accelerated computing. Its platforms power AI, data center, gaming, professional visualization, and automotive markets.",
        "segment_1_name": "Data Center",
        "segment_1_rev": "47,525",
        "segment_2_name": "Gaming",
        "segment_2_rev": "10,447",
        "segment_3_name": "Professional Visualization",
        "segment_3_rev": "1,553",
        "segment_4_name": "Automotive",
        "segment_4_rev": "1,091",
        "risk_1_topic": "Concentration in a small number of large data center customers",
        "risk_2_topic": "Export controls on advanced AI chips affecting sales to China",
        "risk_3_topic": "Single source manufacturing dependence on TSMC",
        "cyber": "The Company reported one cybersecurity incident of limited scope. Customer and financial data were not affected.",
    },
    {
        "filename": "Netflix_2023_10K.pdf",
        "name": "Netflix, Inc.",
        "short": "NFLX",
        "ceo": "Ted Sarandos and Greg Peters",
        "auditor": "Ernst and Young LLP",
        "period": "December 31, 2023",
        "revenue_fy": "$33,723",
        "revenue_prev": "$31,616",
        "revenue_change": "+6.7 percent",
        "gross_margin": "41.5 percent",
        "op_margin": "20.6 percent",
        "net_income": "$5,408",
        "eps": "$12.03",
        "cfo": "$7,267",
        "capex": "$349",
        "rnd": "$2,769 million    (8.2 percent of revenue)",
        "employees": "13,000",
        "business": "Netflix is the world largest streaming entertainment service, providing TV series, documentaries, feature films, and games to paid members across more than 190 countries.",
        "segment_1_name": "United States and Canada",
        "segment_1_rev": "14,977",
        "segment_2_name": "Europe, Middle East, Africa",
        "segment_2_rev": "10,564",
        "segment_3_name": "Latin America",
        "segment_3_rev": "4,539",
        "segment_4_name": "Asia Pacific",
        "segment_4_rev": "3,643",
        "risk_1_topic": "Membership churn and slowing subscriber growth in mature markets",
        "risk_2_topic": "Content production cost inflation and strike related delays",
        "risk_3_topic": "Competition from other streaming services and free ad supported platforms",
        "cyber": "No material cybersecurity incidents were reported in fiscal 2023.",
    },
    {
        "filename": "Ferrari_2023_20F.pdf",
        "name": "Ferrari N.V.",
        "short": "RACE",
        "ceo": "Benedetto Vigna",
        "auditor": "Ernst and Young Accountants LLP",
        "period": "December 31, 2023",
        "revenue_fy": "EUR 5,970",
        "revenue_prev": "EUR 5,095",
        "revenue_change": "+17.2 percent",
        "gross_margin": "49.9 percent",
        "op_margin": "27.3 percent",
        "net_income": "EUR 1,257",
        "eps": "EUR 6.89",
        "cfo": "EUR 1,541",
        "capex": "EUR 888",
        "rnd": "EUR 942 million    (15.8 percent of revenue)",
        "employees": "4,930",
        "business": "Ferrari designs, manufactures, and sells the world most recognised luxury performance sports cars, with deliveries in over 60 markets through an exclusive dealer network.",
        "segment_1_name": "Cars and spare parts",
        "segment_1_rev": "5,001",
        "segment_2_name": "Engines",
        "segment_2_rev": "176",
        "segment_3_name": "Sponsorship and racing",
        "segment_3_rev": "571",
        "segment_4_name": "Other",
        "segment_4_rev": "222",
        "risk_1_topic": "Luxury demand sensitivity to macroeconomic cycles and FX",
        "risk_2_topic": "Transition to electrified powertrains and regulatory compliance",
        "risk_3_topic": "Brand exclusivity management and delivery volume discipline",
        "cyber": "No material cybersecurity incidents were disclosed for the reporting period.",
    },
]


def page(doc, lines, *, title="", size=11, y0=72, gap=18):
    p = doc.new_page(width=612, height=792)
    y = y0
    if title:
        p.insert_text((72, y), title, fontsize=16, fontname="helv")
        y += gap * 2
    for line in lines:
        p.insert_text((72, y), line, fontsize=size, fontname="helv")
        y += gap
        if y > 740: break


def build(issuer: dict) -> Path:
    doc = fitz.open()
    # Cover
    page(doc, [
        "",
        "FORM 10-K  (Annual Report)",
        "",
        f"For the fiscal year ended {issuer['period']}",
        "",
        f"Commission File Number: 001-00000",
        "",
        issuer["name"],
        "",
        f"Ticker: {issuer['short']}",
        f"Independent Registered Public Accounting Firm: {issuer['auditor']}",
        f"Chief Executive Officer: {issuer['ceo']}",
    ], title="")

    # Item 1 Business
    page(doc, [
        issuer["business"],
        "",
        f"As of {issuer['period']} the Company had approximately {issuer['employees']}",
        "full time employees worldwide.",
        "",
        f"Products and services. Revenue is organized across the following reportable segments:",
        f"   {issuer['segment_1_name']},  {issuer['segment_2_name']},",
        f"   {issuer['segment_3_name']},  {issuer['segment_4_name']}.",
        "",
        "Customers. The Company sells through a global distribution and partner network.",
        "Revenue concentration across top customers is disclosed in the financial statements.",
        "",
        f"Research and development. Fiscal year investment: {issuer['rnd']}.",
    ], title="Item 1. Business")

    # Item 1A Risk Factors
    page(doc, [
        "An investment in our common stock involves a high degree of risk.",
        "",
        f"1.  {issuer['risk_1_topic']}.",
        "",
        f"2.  {issuer['risk_2_topic']}.",
        "",
        f"3.  {issuer['risk_3_topic']}.",
        "",
        "Cybersecurity. " + issuer["cyber"],
        "",
        "Regulatory. Certain of the Company products and operations are subject to export",
        "control, sanctions, or sector specific regulation. Changes in such regulation could",
        "limit the Company ability to operate in certain jurisdictions.",
    ], title="Item 1A. Risk Factors")

    # Item 7 MD&A overview
    page(doc, [
        "The following discussion should be read together with the consolidated financial",
        "statements and related notes included elsewhere in this Annual Report.",
        "",
        f"Overview. Total revenue for the fiscal year was {issuer['revenue_fy']} million,",
        f"compared with {issuer['revenue_prev']} million in the prior year, representing a",
        f"change of {issuer['revenue_change']}.",
        "",
        f"Gross margin was {issuer['gross_margin']}. Operating margin was {issuer['op_margin']}.",
        "",
        f"Net income for the fiscal year was {issuer['net_income']} million and diluted",
        f"earnings per share were {issuer['eps']}.",
        "",
        f"Cash generated from operating activities totaled {issuer['cfo']} million.",
        f"Capital expenditure was {issuer['capex']} million.",
    ], title="Item 7. Management's Discussion and Analysis")

    # Revenue by segment table
    p = doc.new_page(width=612, height=792)
    p.insert_text((72, 72), "Item 7. MD&A (continued) — Revenue by Segment",
                  fontsize=14, fontname="helv")
    p.insert_text((72, 110),
                  f"The following table presents revenue by reportable segment ({issuer['short']} fiscal year, in millions):",
                  fontsize=11, fontname="helv")
    rows = [
        ["Segment",                    "FY current",               ""],
        [issuer["segment_1_name"],     issuer["segment_1_rev"],    ""],
        [issuer["segment_2_name"],     issuer["segment_2_rev"],    ""],
        [issuer["segment_3_name"],     issuer["segment_3_rev"],    ""],
        [issuer["segment_4_name"],     issuer["segment_4_rev"],    ""],
        ["Total revenue",              issuer["revenue_fy"].replace("$", "").replace("EUR ", ""), ""],
    ]
    col_x = [72, 320, 460]
    row_y = 150
    for i, row in enumerate(rows):
        bold = (i == 0) or (row[0] == "Total revenue")
        for xi, cell in enumerate(row):
            p.insert_text((col_x[xi], row_y), cell, fontsize=11,
                          fontname=("hebo" if bold else "helv"))
        if i == 0 or row[0] == "Total revenue":
            p.draw_line((72, row_y + 4), (540, row_y + 4))
        row_y += 24

    p.insert_text((72, 330), "Key metrics summary:", fontsize=12, fontname="hebo")
    metrics = [
        f"Total revenue              {issuer['revenue_fy']} million    ({issuer['revenue_change']} YoY)",
        f"Gross margin               {issuer['gross_margin']}",
        f"Operating margin           {issuer['op_margin']}",
        f"Net income                 {issuer['net_income']} million",
        f"Diluted EPS                {issuer['eps']}",
        f"Cash from operations       {issuer['cfo']} million",
        f"Capital expenditure        {issuer['capex']} million",
        f"Research and development   {issuer['rnd']}",
    ]
    y = 360
    for m in metrics:
        p.insert_text((72, y), m, fontsize=11, fontname="helv")
        y += 22

    # Item 7 liquidity
    page(doc, [
        f"The Company generated {issuer['cfo']} million of cash from operations during the",
        "fiscal year. Capital expenditure was primarily directed toward expansion of",
        "research and development infrastructure and production capacity.",
        "",
        "The Company maintains a strong liquidity position supported by cash, cash",
        "equivalents, and marketable securities. Management believes that existing",
        "liquidity and expected operating cash flows will be sufficient to fund ongoing",
        "operating needs and capital investment for at least the next twelve months.",
        "",
        "During the fiscal year the Company continued to execute its shareholder return",
        "program through share repurchases and, where applicable, dividends.",
    ], title="Item 7. MD&A (continued) — Liquidity and Capital Resources")

    # Market risk
    page(doc, [
        "Foreign currency risk. A meaningful portion of revenue and cost of revenue is",
        "denominated in currencies other than the reporting currency. The Company uses",
        "selective hedging to mitigate a portion of this exposure.",
        "",
        "Interest rate risk. The marketable securities portfolio is managed primarily to",
        "preserve principal and provide liquidity, with a short weighted average duration.",
        "",
        "Commodity and input cost risk. Prices of key components and inputs can fluctuate",
        "materially. Material input cost increases, if not offset by pricing or productivity,",
        "could compress gross margin.",
    ], title="Item 7A. Quantitative and Qualitative Disclosures About Market Risk")

    # Auditor
    page(doc, [
        "Report of Independent Registered Public Accounting Firm.",
        "",
        f"To the Stockholders and the Board of Directors of {issuer['name']}.",
        "",
        "Opinion on the Financial Statements. We have audited the accompanying",
        "consolidated balance sheets of the Company, and the related consolidated",
        "statements of operations, comprehensive income, stockholders' equity, and cash",
        f"flows for the fiscal year ended {issuer['period']}, and the related notes.",
        "",
        "In our opinion, the consolidated financial statements present fairly, in all",
        "material respects, the financial position of the Company, and the results of",
        "its operations and its cash flows for the fiscal year then ended, in conformity",
        "with applicable accounting standards.",
        "",
        f"{issuer['auditor']}",
        f"Date: soon after {issuer['period']}",
    ], title="Item 8. Financial Statements and Supplementary Data")

    # Governance
    page(doc, [
        "Board of Directors.",
        "",
        f"Chief Executive Officer. {issuer['ceo']}.",
        "",
        "The Board currently consists of independent directors and the CEO. The Board",
        "has three standing committees: Audit, Compensation, and Nominating and Corporate",
        "Governance. Each committee is composed exclusively of independent directors.",
        "",
        "Executive Compensation. Elements of executive compensation include base salary,",
        "annual incentive tied to revenue and operating margin targets, and long term",
        "equity awards that vest over four years subject to continued service.",
    ], title="Item 10 through 14. Directors, Officers, Governance, and Compensation")

    # Additional narrative page
    page(doc, [
        "Outlook.",
        "",
        "Management expects continued investment in research and development, disciplined",
        "operating expense management, and a focus on sustainable long term growth across",
        "the Company reportable segments. Forward looking statements are subject to risks",
        "and uncertainties described elsewhere in this Annual Report.",
        "",
        "Sustainability.",
        "",
        "The Company continues to progress its environmental and social commitments,",
        "including energy efficiency improvements at major facilities and progress toward",
        "supply chain transparency.",
    ], title="Outlook and Sustainability")

    out = OUT / issuer["filename"]
    doc.save(out)
    return out


for issuer in ISSUERS:
    path = build(issuer)
    print(f"wrote {path.name}  ({path.stat().st_size} bytes)")

print("done.  Drop all 4 into the matrix via ⌘K → Add documents.")
