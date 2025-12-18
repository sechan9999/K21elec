
import React, { useState, useMemo } from 'react';
import * as pdfjsLib from 'pdfjs-dist';
import { extractDataFromImage } from './services/geminiService';
import { ElectionPageData, AggregatedData, SummaryByCategory } from './types';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts';

// Set up PDF.js worker
pdfjsLib.GlobalWorkerOptions.workerSrc = `https://esm.sh/pdfjs-dist@${pdfjsLib.version}/build/pdf.worker.mjs`;

const TARGET_CANDIDATES = ["이재명", "김문수", "이준석", "권영국", "송진호"];

const App: React.FC = () => {
  const [files, setFiles] = useState<File[]>([]);
  const [results, setResults] = useState<ElectionPageData[]>([]);
  const [isProcessing, setIsProcessing] = useState(false);
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [selectedCandidates, setSelectedCandidates] = useState<string[]>(TARGET_CANDIDATES);

  const toggleCandidate = (candidate: string) => {
    setSelectedCandidates(prev =>
      prev.includes(candidate)
        ? prev.filter(c => c !== candidate)
        : [...prev, candidate]
    );
  };

  const selectAllCandidates = () => setSelectedCandidates(TARGET_CANDIDATES);
  const clearAllCandidates = () => setSelectedCandidates([]);

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files) {
      setFiles(Array.from(e.target.files));
      setError(null);
    }
  };

  const renderPageToDataUrl = async (page: any): Promise<string> => {
    const viewport = page.getViewport({ scale: 2.5 }); // Higher scale for better OCR
    const canvas = document.createElement('canvas');
    const context = canvas.getContext('2d');
    canvas.height = viewport.height;
    canvas.width = viewport.width;
    if (!context) throw new Error('Canvas context error');
    await page.render({ canvasContext: context, viewport }).promise;
    return canvas.toDataURL('image/png');
  };

  const processFile = async (file: File, startIndex: number, totalFiles: number) => {
    if (file.type === 'application/pdf') {
      const arrayBuffer = await file.arrayBuffer();
      const pdf = await pdfjsLib.getDocument({ data: arrayBuffer }).promise;
      const pagesCount = pdf.numPages;

      for (let i = 1; i <= pagesCount; i++) {
        const page = await pdf.getPage(i);
        const dataUrl = await renderPageToDataUrl(page);
        try {
          const data = await extractDataFromImage(dataUrl);
          
          let mappedType = data.votingType;
          if (i >= 1 && i <= 26) mappedType = "관내사전 (Early In)";
          else if (i >= 27 && i <= 168) mappedType = "선거일 (Election Day)";
          else if (i === 169) mappedType = "관외사전 (Early Out)";
          else if (i === 170) mappedType = "재외투표 (Overseas)";
          else if (i === 171) mappedType = "거소/선상 (Absentee)";

          setResults(prev => [...prev, { ...data, votingType: mappedType, pageNumber: i }]);
        } catch (err) {
          console.error(`Page ${i} failed:`, err);
        }
        setProgress(Math.round(((startIndex + (i / pagesCount)) / totalFiles) * 100));
      }
    }
  };

  const startExtraction = async () => {
    if (files.length === 0) return;
    setIsProcessing(true);
    setResults([]);
    setProgress(0);
    setError(null);

    try {
      for (let i = 0; i < files.length; i++) {
        await processFile(files[i], i, files.length);
      }
    } catch (err) {
      setError(`Extraction failed: ${err instanceof Error ? err.message : 'Unknown error'}`);
    } finally {
      setIsProcessing(false);
      setProgress(100);
    }
  };

  const districtSummary = useMemo(() => {
    const map: Record<string, AggregatedData> = {};
    results.forEach(page => {
      const key = page.district || "Unknown";
      if (!map[key]) {
        map[key] = { district: key, votesByCandidate: {}, validTotal: 0, invalidTotal: 0, grandTotal: 0 };
      }
      const entry = map[key];
      entry.validTotal += page.validVotes;
      entry.invalidTotal += page.invalidVotes;
      entry.grandTotal += page.totalVotes;
      page.candidateVotes.forEach(cv => {
        if (!entry.votesByCandidate[cv.candidateName]) {
          entry.votesByCandidate[cv.candidateName] = { classified: 0, reconfirm: 0, total: 0 };
        }
        const cEntry = entry.votesByCandidate[cv.candidateName];
        cEntry.classified += cv.classifiedVotes;
        cEntry.reconfirm += cv.reconfirmVotes;
        cEntry.total += cv.totalVotes;
      });
    });
    return Object.values(map);
  }, [results]);

  const downloadCSV = () => {
    if (results.length === 0 || selectedCandidates.length === 0) return;
    let headers = "투표구,유형,유효투표,무효투표,총계";
    selectedCandidates.forEach(c => {
      headers += `,${c}_분류,${c}_재확인,${c}_계`;
    });
    let csv = headers + "\n";

    results.forEach(r => {
      let row = `"${r.district}","${r.votingType}",${r.validVotes},${r.invalidVotes},${r.totalVotes}`;
      selectedCandidates.forEach(c => {
        const cv = r.candidateVotes.find(v => v.candidateName === c);
        row += `,${cv?.classifiedVotes || 0},${cv?.reconfirmVotes || 0},${cv?.totalVotes || 0}`;
      });
      csv += row + "\n";
    });

    // Add totals row
    let totalRow = `"전체 합계","",${results.reduce((a, b) => a + b.validVotes, 0)},${results.reduce((a, b) => a + b.invalidVotes, 0)},${results.reduce((a, b) => a + b.totalVotes, 0)}`;
    selectedCandidates.forEach(c => {
      const s = results.reduce((acc, r) => acc + (r.candidateVotes.find(cv => cv.candidateName === c)?.classifiedVotes || 0), 0);
      const rc = results.reduce((acc, r) => acc + (r.candidateVotes.find(cv => cv.candidateName === c)?.reconfirmVotes || 0), 0);
      const t = results.reduce((acc, r) => acc + (r.candidateVotes.find(cv => cv.candidateName === c)?.totalVotes || 0), 0);
      totalRow += `,${s},${rc},${t}`;
    });
    csv += totalRow + "\n";

    const blob = new Blob(["\uFEFF" + csv], { type: 'text/csv;charset=utf-8;' });
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = `21대대선_심사집계부_${selectedCandidates.length}명.csv`;
    link.click();
  };

  return (
    <div className="min-h-screen bg-slate-50 p-4 md:p-8 font-sans">
      <header className="max-w-7xl mx-auto mb-12 text-center">
        <h1 className="text-5xl font-black text-slate-900 mb-4 tracking-tighter">21대 대선 개표 감사 시스템</h1>
        <p className="text-slate-500 font-medium mb-6">심사·집계부 분석: 분류된 투표지 vs 재확인대상 투표지</p>

        {/* Candidate Filter Section */}
        <div className="bg-white rounded-2xl p-6 shadow-lg border border-slate-100 inline-block">
          <div className="flex items-center gap-4 mb-4">
            <span className="text-sm font-black text-slate-400 uppercase tracking-widest">후보자 필터</span>
            <button
              onClick={selectAllCandidates}
              className="text-xs font-bold text-indigo-600 hover:text-indigo-700 px-2 py-1 bg-indigo-50 rounded-lg hover:bg-indigo-100 transition-all"
            >
              전체선택
            </button>
            <button
              onClick={clearAllCandidates}
              className="text-xs font-bold text-slate-500 hover:text-slate-700 px-2 py-1 bg-slate-50 rounded-lg hover:bg-slate-100 transition-all"
            >
              전체해제
            </button>
          </div>
          <div className="flex justify-center gap-3 flex-wrap">
            {TARGET_CANDIDATES.map((c, idx) => {
              const isSelected = selectedCandidates.includes(c);
              const colors = [
                { bg: 'bg-blue-500', border: 'border-blue-500', light: 'bg-blue-50' },
                { bg: 'bg-red-500', border: 'border-red-500', light: 'bg-red-50' },
                { bg: 'bg-amber-500', border: 'border-amber-500', light: 'bg-amber-50' },
                { bg: 'bg-emerald-500', border: 'border-emerald-500', light: 'bg-emerald-50' },
                { bg: 'bg-purple-500', border: 'border-purple-500', light: 'bg-purple-50' },
              ];
              const color = colors[idx % colors.length];
              return (
                <button
                  key={c}
                  onClick={() => toggleCandidate(c)}
                  className={`px-4 py-2 rounded-xl text-sm font-bold transition-all transform active:scale-95 flex items-center gap-2 ${
                    isSelected
                      ? `${color.bg} text-white shadow-lg`
                      : `${color.light} text-slate-500 border-2 ${color.border} border-opacity-30 hover:border-opacity-60`
                  }`}
                >
                  <span className={`w-4 h-4 rounded-md border-2 flex items-center justify-center ${isSelected ? 'bg-white/30 border-white/50' : 'border-slate-300'}`}>
                    {isSelected && (
                      <svg className="w-3 h-3 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
                      </svg>
                    )}
                  </span>
                  {c}
                </button>
              );
            })}
          </div>
          <div className="mt-3 text-xs text-slate-400">
            선택된 후보자: <span className="font-bold text-slate-600">{selectedCandidates.length}</span> / {TARGET_CANDIDATES.length}
          </div>
        </div>
      </header>

      <main className="max-w-7xl mx-auto space-y-8">
        {/* Upload Panel */}
        <section className="bg-white p-8 rounded-[2rem] shadow-xl border border-slate-100 transition-all hover:shadow-2xl">
          <div className="flex flex-col md:flex-row items-end gap-6">
            <div className="flex-1 w-full">
              <label className="block text-sm font-black text-slate-400 mb-3 uppercase tracking-widest">개표상황표 PDF 선택</label>
              <input
                type="file"
                accept="application/pdf"
                onChange={handleFileChange}
                className="block w-full text-sm text-slate-500 file:mr-4 file:py-3 file:px-8 file:rounded-2xl file:border-0 file:text-sm file:font-black file:bg-indigo-600 file:text-white hover:file:bg-indigo-700 cursor-pointer border-2 border-dashed border-slate-200 rounded-[1.5rem] p-4 bg-slate-50/50"
              />
            </div>
            <button
              onClick={startExtraction}
              disabled={isProcessing || files.length === 0}
              className={`w-full md:w-auto px-12 py-4 rounded-2xl font-black text-lg transition-all transform active:scale-95 shadow-xl ${isProcessing || files.length === 0 ? 'bg-slate-200 text-slate-400 cursor-not-allowed' : 'bg-indigo-600 text-white hover:bg-indigo-700 shadow-indigo-200'}`}
            >
              {isProcessing ? '문서 분석중...' : `개표 감사 시작 (${files.length})`}
            </button>
          </div>

          {isProcessing && (
            <div className="mt-8 animate-in fade-in slide-in-from-bottom-2">
              <div className="flex justify-between mb-3 items-end">
                <span className="text-sm font-black text-indigo-600 uppercase tracking-widest">감사 진행률</span>
                <span className="text-3xl font-black text-indigo-900">{progress}%</span>
              </div>
              <div className="w-full bg-slate-100 rounded-full h-4 overflow-hidden shadow-inner border border-slate-200">
                <div
                  className="bg-gradient-to-r from-indigo-500 via-purple-500 to-pink-500 h-full transition-all duration-500 rounded-full"
                  style={{ width: `${progress}%` }}
                ></div>
              </div>
            </div>
          )}
        </section>

        {results.length > 0 && (
          <div className="space-y-8">
            {/* Breakdown Charts */}
            <section className="grid grid-cols-1 lg:grid-cols-2 gap-8">
              <div className="bg-white p-8 rounded-[2rem] shadow-xl border border-slate-100">
                <h3 className="text-xl font-black mb-6 text-slate-800 flex items-center gap-3">
                   <span className="w-3 h-3 bg-indigo-500 rounded-full animate-ping"></span> 투표구별 유효/무효 투표 현황 (상위 10개)
                </h3>
                <div className="h-[400px]">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={districtSummary.slice(0, 10)}>
                      <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#f1f5f9" />
                      <XAxis dataKey="district" tick={{fontSize: 10, fontWeight: 800, fill: '#64748b'}} axisLine={false} tickLine={false} />
                      <YAxis tick={{fontSize: 10, fill: '#94a3b8'}} axisLine={false} tickLine={false} />
                      <Tooltip 
                        contentStyle={{borderRadius: '1.5rem', border: 'none', boxShadow: '0 25px 50px -12px rgba(0,0,0,0.25)'}} 
                        cursor={{fill: '#f8fafc'}}
                      />
                      <Legend verticalAlign="top" align="right" height={40} iconType="circle" />
                      <Bar dataKey="validTotal" name="유효투표" fill="#6366f1" radius={[4, 4, 0, 0]} barSize={20} />
                      <Bar dataKey="invalidTotal" name="무효투표" fill="#f43f5e" radius={[4, 4, 0, 0]} barSize={20} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </div>

              <div className="bg-white p-8 rounded-[2rem] shadow-xl border border-slate-100 overflow-hidden">
                 <h3 className="text-xl font-black mb-6 text-slate-800">후보자별 득표 신뢰도 분석</h3>
                 <div className="space-y-6">
                    {selectedCandidates.length === 0 ? (
                      <div className="text-center py-8 text-slate-400">
                        <p className="font-bold">후보자를 선택해주세요</p>
                      </div>
                    ) : (
                      TARGET_CANDIDATES.filter(name => selectedCandidates.includes(name)).map((name, i) => {
                        const totalC = results.reduce((acc, r) => acc + (r.candidateVotes.find(cv => cv.candidateName === name)?.totalVotes || 0), 0);
                        const totalS = results.reduce((acc, r) => acc + (r.candidateVotes.find(cv => cv.candidateName === name)?.classifiedVotes || 0), 0);
                        const totalR = results.reduce((acc, r) => acc + (r.candidateVotes.find(cv => cv.candidateName === name)?.reconfirmVotes || 0), 0);
                        const reconfirmRate = totalC > 0 ? (totalR / totalC) * 100 : 0;
                        const colors = ['bg-blue-500', 'bg-red-500', 'bg-amber-500', 'bg-emerald-500', 'bg-purple-500'];
                        const colorIdx = TARGET_CANDIDATES.indexOf(name);

                        return (
                          <div key={name} className="relative">
                            <div className="flex justify-between items-end mb-2">
                               <span className="text-sm font-black text-slate-700">{name}</span>
                               <span className="text-[10px] font-bold text-slate-400 uppercase">재확인율: {reconfirmRate.toFixed(2)}%</span>
                            </div>
                            <div className="w-full bg-slate-50 h-3 rounded-full overflow-hidden flex shadow-inner">
                               <div className={`h-full ${colors[colorIdx]}`} style={{ width: `${totalC > 0 ? (totalS/totalC)*100 : 0}%` }}></div>
                               <div className="h-full bg-amber-400" style={{ width: `${reconfirmRate}%` }}></div>
                            </div>
                            <div className="flex gap-4 mt-1">
                               <span className="text-[10px] font-bold text-slate-600">분류: {totalS.toLocaleString()}</span>
                               <span className="text-[10px] font-bold text-amber-500">재확인: {totalR.toLocaleString()}</span>
                               <span className="text-[10px] font-bold text-slate-900">총계: {totalC.toLocaleString()}</span>
                            </div>
                          </div>
                        );
                      })
                    )}
                 </div>
              </div>
            </section>

            {/* Detailed Audit Table */}
            <section className="bg-white rounded-[2rem] shadow-2xl border border-slate-100 overflow-hidden">
              <div className="p-8 border-b border-slate-50 bg-white flex flex-col md:flex-row justify-between items-center gap-6">
                <div>
                  <h2 className="text-3xl font-black text-slate-900 tracking-tighter">심사·집계부 상세 보고서</h2>
                  <p className="text-slate-500 font-bold text-sm mt-1 uppercase tracking-widest">21대 대선 개표 감사</p>
                </div>
                <button
                  onClick={downloadCSV}
                  disabled={selectedCandidates.length === 0}
                  className={`flex items-center gap-3 px-10 py-4 rounded-2xl transition-all font-black shadow-lg active:scale-95 ${
                    selectedCandidates.length === 0
                      ? 'bg-slate-200 text-slate-400 cursor-not-allowed shadow-none'
                      : 'bg-emerald-600 text-white hover:bg-emerald-700 shadow-emerald-100'
                  }`}
                >
                  <svg xmlns="http://www.w3.org/2000/svg" className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                  </svg>
                  CSV 내보내기 ({selectedCandidates.length}명)
                </button>
              </div>
              {selectedCandidates.length === 0 ? (
                <div className="p-12 text-center text-slate-400">
                  <p className="font-bold text-lg">표시할 후보자를 선택해주세요</p>
                  <p className="text-sm mt-2">상단의 후보자 필터에서 최소 1명 이상을 선택하세요</p>
                </div>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-left border-collapse">
                    <thead>
                      <tr className="bg-slate-50/50 text-[10px] font-black text-slate-400 uppercase tracking-widest border-b border-slate-100">
                        <th className="px-6 py-8 sticky left-0 bg-slate-50 z-20" rowSpan={2}>투표구 / 유형</th>
                        <th className="px-6 py-4 text-center border-l border-slate-200" colSpan={3}>투표 요약</th>
                        {selectedCandidates.map(name => {
                          const colorIdx = TARGET_CANDIDATES.indexOf(name);
                          const colors = ['text-blue-600', 'text-red-600', 'text-amber-600', 'text-emerald-600', 'text-purple-600'];
                          return (
                            <th key={name} className={`px-6 py-4 text-center border-l border-slate-200 ${colors[colorIdx]}`} colSpan={3}>{name}</th>
                          );
                        })}
                      </tr>
                      <tr className="bg-slate-50/50 text-[10px] font-black text-slate-400 uppercase tracking-widest border-b border-slate-100">
                        <th className="px-4 py-4 border-l border-slate-100 text-right">유효</th>
                        <th className="px-4 py-4 text-right">무효</th>
                        <th className="px-4 py-4 text-right">총계</th>
                        {selectedCandidates.map(name => (
                          <React.Fragment key={name}>
                            <th className="px-4 py-4 border-l border-slate-100 text-right text-indigo-600 italic">분류</th>
                            <th className="px-4 py-4 text-right text-amber-600 italic">재확인</th>
                            <th className="px-4 py-4 text-right font-black text-slate-900 bg-slate-100/30">계</th>
                          </React.Fragment>
                        ))}
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100">
                      {results.map((r, idx) => (
                        <tr key={idx} className="hover:bg-slate-50/80 transition-all group">
                          <td className="px-6 py-6 sticky left-0 bg-white group-hover:bg-slate-50 z-10">
                            <div className="font-black text-slate-900 text-lg leading-none mb-1">{r.district}</div>
                            <div className="text-[10px] font-bold text-slate-400 uppercase tracking-tighter">{r.votingType}</div>
                          </td>
                          <td className="px-4 py-6 text-right font-mono text-sm border-l border-slate-100 font-bold text-emerald-600">{r.validVotes.toLocaleString()}</td>
                          <td className="px-4 py-6 text-right font-mono text-sm text-rose-500">{r.invalidVotes.toLocaleString()}</td>
                          <td className="px-4 py-6 text-right font-mono text-sm font-black bg-slate-50/30">{r.totalVotes.toLocaleString()}</td>
                          {selectedCandidates.map(name => {
                            const cv = r.candidateVotes.find(v => v.candidateName === name);
                            const colorIdx = TARGET_CANDIDATES.indexOf(name);
                            const colors = ['text-blue-500', 'text-red-500', 'text-amber-500', 'text-emerald-500', 'text-purple-500'];
                            return (
                              <React.Fragment key={name}>
                                <td className={`px-4 py-6 text-right font-mono text-sm border-l border-slate-100 ${colors[colorIdx]}`}>{cv?.classifiedVotes.toLocaleString() || 0}</td>
                                <td className="px-4 py-6 text-right font-mono text-sm text-amber-500">{cv?.reconfirmVotes.toLocaleString() || 0}</td>
                                <td className="px-4 py-6 text-right font-mono text-sm font-black text-slate-900 bg-slate-50/30">{cv?.totalVotes.toLocaleString() || 0}</td>
                              </React.Fragment>
                            );
                          })}
                        </tr>
                      ))}
                      {/* Sum Row */}
                      <tr className="bg-slate-900 text-white font-black text-xs">
                        <td className="px-6 py-8 sticky left-0 bg-slate-900 z-10 uppercase tracking-widest">전체 합계</td>
                        <td className="px-4 py-8 text-right font-mono text-emerald-400 border-l border-slate-800">
                          {results.reduce((a, b) => a + b.validVotes, 0).toLocaleString()}
                        </td>
                        <td className="px-4 py-8 text-right font-mono text-rose-400">
                          {results.reduce((a, b) => a + b.invalidVotes, 0).toLocaleString()}
                        </td>
                        <td className="px-4 py-8 text-right font-mono bg-white/5">
                          {results.reduce((a, b) => a + b.totalVotes, 0).toLocaleString()}
                        </td>
                        {selectedCandidates.map(name => {
                          const s = results.reduce((acc, r) => acc + (r.candidateVotes.find(cv => cv.candidateName === name)?.classifiedVotes || 0), 0);
                          const rc = results.reduce((acc, r) => acc + (r.candidateVotes.find(cv => cv.candidateName === name)?.reconfirmVotes || 0), 0);
                          const t = results.reduce((acc, r) => acc + (r.candidateVotes.find(cv => cv.candidateName === name)?.totalVotes || 0), 0);
                          return (
                            <React.Fragment key={name}>
                              <td className="px-4 py-8 text-right font-mono border-l border-slate-800 text-indigo-300">{s.toLocaleString()}</td>
                              <td className="px-4 py-8 text-right font-mono text-amber-300">{rc.toLocaleString()}</td>
                              <td className="px-4 py-8 text-right font-mono bg-white/5 text-lg">{t.toLocaleString()}</td>
                            </React.Fragment>
                          );
                        })}
                      </tr>
                    </tbody>
                  </table>
                </div>
              )}
            </section>
          </div>
        )}

        {!isProcessing && results.length === 0 && (
          <div className="flex flex-col items-center justify-center py-48 bg-white rounded-[3rem] border-4 border-dashed border-slate-100 shadow-inner">
             <div className="relative mb-10">
                <div className="absolute inset-0 bg-indigo-500 rounded-full blur-3xl opacity-20 animate-pulse"></div>
                <div className="relative p-10 bg-indigo-50 rounded-full">
                  <svg xmlns="http://www.w3.org/2000/svg" className="h-24 w-24 text-indigo-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1} d="M19.428 15.428a2 2 0 00-1.022-.547l-2.387-.477a6 6 0 00-3.86.517l-.318.158a6 6 0 01-3.86.517L6.05 15.21a2 2 0 00-1.806.547M8 4h8l-1 1v5.172a2 2 0 00.586 1.414l5 5c1.26 1.26.367 3.414-1.415 3.414H4.828c-1.782 0-2.674-2.154-1.414-3.414l5-5A2 2 0 009 10.172V5L8 4z" />
                  </svg>
                </div>
             </div>
             <h3 className="text-4xl font-black text-slate-300 tracking-tighter">개표 감사 준비 완료</h3>
             <p className="text-slate-400 mt-3 font-black uppercase tracking-widest text-sm italic">분류된 투표지 vs 재확인대상 투표지 분석</p>
          </div>
        )}
      </main>

      <footer className="mt-24 pb-16 text-center">
         <div className="inline-flex gap-4 p-2 bg-white rounded-2xl shadow-sm border border-slate-100">
            <span className="px-4 py-1.5 bg-indigo-50 text-indigo-700 text-[10px] font-black rounded-xl uppercase tracking-widest">심사·집계부 감사 도구</span>
            <span className="px-4 py-1.5 bg-slate-50 text-slate-400 text-[10px] font-black rounded-xl uppercase tracking-widest">Gemini 3 Vision AI</span>
         </div>
         <p className="mt-6 text-slate-300 text-xs font-bold tracking-widest">21대 대선 개표 감사 시스템</p>
      </footer>
    </div>
  );
};

export default App;
