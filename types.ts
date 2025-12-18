
export interface CandidateVote {
  candidateName: string;
  classifiedVotes: number; // 분류된 투표지 (a)
  reconfirmVotes: number;  // 재확인대상 투표지 (b)
  totalVotes: number;      // 계 (a+b)
}

export interface ElectionPageData {
  pageNumber?: number;
  district: string;
  votingType: string;
  candidateVotes: CandidateVote[];
  validVotes: number;
  invalidVotes: number;
  totalVotes: number;
}

export interface AggregatedData {
  district: string;
  votesByCandidate: Record<string, {
    classified: number;
    reconfirm: number;
    total: number;
  }>;
  validTotal: number;
  invalidTotal: number;
  grandTotal: number;
}

export interface SummaryByCategory {
  category: string;
  validTotal: number;
  invalidTotal: number;
  grandTotal: number;
}
