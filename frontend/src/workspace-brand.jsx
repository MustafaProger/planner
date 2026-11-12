import React from "react";

export function WorkspaceBrand() {
  return (
    <>
      <img className="wordmark-icon" src={`${import.meta.env.BASE_URL}favicon.png`} alt="" width="24" height="24" />
      CharterStats<span aria-hidden="true"> / </span>
    </>
  );
}
