
import { GoogleGenAI, Type, GenerateContentResponse } from "@google/genai";
import { ElectionPageData } from "../types";

const SYSTEM_INSTRUCTION = `
You are a highly precise OCR and data extraction expert for South Korean election documents (개표상황표).
Focus on extracting the breakdown from the "심사·집계부" (Examination/Tally) section for specific candidates.

CRITICAL INSTRUCTIONS:
1. Target Candidates: ONLY extract data for these 5 candidates:
   - 이재명
   - 김문수
   - 이준석
   - 권영국
   - 송진호

2. Table to Target: Focus on the "심사·집계부" table.
   - Extract "분류된 투표지" (Classified/Sorted votes, often column 'a').
   - Extract "재확인대상 투표지" (Votes for reconfirmation, often column 'b').
   - Extract "계" (Total candidate votes, a+b).

3. District & Type:
   - District: Identify from Section 1 "투표구명" (e.g., '한림읍', '애월읍').
   - Voting Type: Identify from the header or brackets (e.g., '관내사전', '선거일').

4. Overall Summary:
   - Valid Votes (유효투표수 계)
   - Invalid Votes (무효투표수)
   - Total Votes (총계/투표수)

5. Data Cleaning: Clean all commas and non-numeric characters. Return 0 if data is missing for a candidate.
`;

export const extractDataFromImage = async (base64Image: string): Promise<ElectionPageData> => {
  const ai = new GoogleGenAI({ apiKey: process.env.API_KEY || '' });
  
  const response = await ai.models.generateContent({
    model: "gemini-3-flash-preview",
    contents: [
      {
        parts: [
          { inlineData: { mimeType: "image/png", data: base64Image.split(',')[1] || base64Image } },
          { text: "Extract detailed counts (Sorted, Reconfirm, Total) for 이재명, 김문수, 이준석, 권영국, 송진호 from the '심사·집계부' table. Return JSON." }
        ]
      }
    ],
    config: {
      systemInstruction: SYSTEM_INSTRUCTION,
      responseMimeType: "application/json",
      responseSchema: {
        type: Type.OBJECT,
        properties: {
          district: { type: Type.STRING },
          votingType: { type: Type.STRING },
          candidateVotes: {
            type: Type.ARRAY,
            items: {
              type: Type.OBJECT,
              properties: {
                candidateName: { type: Type.STRING },
                classifiedVotes: { type: Type.NUMBER, description: "분류된 투표지" },
                reconfirmVotes: { type: Type.NUMBER, description: "재확인대상 투표지" },
                totalVotes: { type: Type.NUMBER, description: "계 (a+b)" }
              },
              required: ["candidateName", "classifiedVotes", "reconfirmVotes", "totalVotes"]
            }
          },
          validVotes: { type: Type.NUMBER },
          invalidVotes: { type: Type.NUMBER },
          totalVotes: { type: Type.NUMBER }
        },
        required: ["district", "votingType", "candidateVotes", "validVotes", "invalidVotes", "totalVotes"]
      }
    }
  });

  const text = response.text;
  if (!text) throw new Error("No response from AI");
  
  return JSON.parse(text) as ElectionPageData;
};
