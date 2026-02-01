import React from 'react';
import './ProgressGrid.css';

export default function ProgressGrid({ modelStates, maxIterations }) {
  if (!modelStates || Object.keys(modelStates).length === 0) {
    return null;
  }

  const models = Object.keys(modelStates);
  const readyCount = models.filter(m => modelStates[m].status === 'ready').length;

  return (
    <div className="progress-grid">
      <table>
        <thead>
          <tr>
            <th>Model</th>
            {Array.from({ length: maxIterations }, (_, i) => (
              <th key={i}>R{i + 1}</th>
            ))}
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {models.map(modelId => {
            const state = modelStates[modelId];
            const shortName = modelId.split('/').pop();

            return (
              <tr key={modelId}>
                <td className="model-name">{shortName}</td>
                {Array.from({ length: maxIterations }, (_, i) => {
                  const roundNum = i + 1;
                  let symbol = '·'; // Not started

                  if (state.status === 'ready' && state.rounds === roundNum) {
                    symbol = '●'; // Finished here
                  } else if (state.rounds > roundNum) {
                    symbol = '✓'; // Completed, continued
                  } else if (state.rounds === roundNum && state.status !== 'ready') {
                    symbol = '⏳'; // In progress
                  } else if (state.status === 'ready' && state.rounds < roundNum) {
                    symbol = '—'; // Skipped
                  }

                  return <td key={i} className="round-cell">{symbol}</td>;
                })}
                <td className="status-cell">
                  {state.status === 'ready' ? '✓ READY' : 'Thinking...'}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <div className="progress-summary">
        {readyCount}/{models.length} ready
      </div>
    </div>
  );
}
