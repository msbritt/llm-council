import React from 'react';
import './IterationRound.css';

export default function IterationRound({ round }) {
  const { roundNum, duration, modelStatuses, questions, userAnswers } = round;

  // Format duration
  const formatDuration = (seconds) => {
    if (seconds < 1) return `${Math.round(seconds * 1000)}ms`;
    if (seconds < 60) return `${Math.round(seconds)}s`;
    const mins = Math.floor(seconds / 60);
    const secs = Math.round(seconds % 60);
    return `${mins}m ${secs}s`;
  };

  // Extract model name from full ID
  const getModelName = (modelId) => {
    return modelId.split('/').pop();
  };

  // Check if all models are ready
  const allReady = Object.values(modelStatuses).every(s => s.status === 'ready');

  return (
    <div className="iteration-round">
      <div className="round-header">
        <h3>ITERATION ROUND {roundNum} ({formatDuration(duration)})</h3>
        {allReady && <span className="all-ready-badge">✓ All models ready</span>}
      </div>

      <div className="model-statuses">
        <h4>Model Status:</h4>
        {Object.entries(modelStatuses).map(([modelId, status]) => (
          <div key={modelId} className="model-status">
            <span className={`status-icon ${status.status}`}>
              {status.status === 'ready' ? '✓' : '⏳'}
            </span>
            <span className="model-name">{getModelName(modelId)}</span>
            <span className="model-timing">({formatDuration(status.timing)})</span>
            <span className="model-state">
              {status.status === 'ready' ? 'Ready' : 'Requesting information'}
            </span>
          </div>
        ))}
      </div>

      {questions && questions.length > 0 && (
        <div className="round-questions-display">
          <h4>Questions Asked:</h4>
          {questions.map((q, idx) => (
            <div key={idx} className="question-display">
              <div className="question-text">
                <strong>{idx + 1}.</strong> {q.text}
              </div>
              <div className="asked-by">
                Asked by: {q.asked_by.map(getModelName).join(', ')}
              </div>
              {userAnswers[q.text] && (
                <div className="user-answer">
                  <strong>Your answer:</strong> {userAnswers[q.text]}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {questions.length === 0 && (
        <div className="no-questions">
          <p>✓ No questions needed - all models had sufficient information</p>
        </div>
      )}
    </div>
  );
}
