import type { Shape } from "./api/types";

export interface TemplateColumn {
  prompt: string;
  shape: Shape;
}

export const TEMPLATES: Record<string, TemplateColumn[]> = {
  "Risk extraction": [
    { prompt: "Top 3 material risk factors", shape: "list" },
    { prompt: "Supply chain concentration", shape: "text" },
    { prompt: "Cybersecurity incidents disclosed", shape: "list" },
    { prompt: "Regulatory / legal proceedings", shape: "text" },
  ],
  "Revenue & margins": [
    { prompt: "Total revenue (fiscal year)", shape: "currency" },
    { prompt: "YoY revenue growth %", shape: "percentage" },
    { prompt: "Operating margin %", shape: "percentage" },
    { prompt: "Gross margin %", shape: "percentage" },
  ],
  "Auditor & governance": [
    { prompt: "Independent auditor", shape: "text" },
    { prompt: "Auditor opinion type", shape: "text" },
    { prompt: "CEO name", shape: "text" },
    { prompt: "Board size", shape: "number" },
  ],
};
